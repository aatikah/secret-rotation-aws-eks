# EKS environment: fully Terraform-managed EKS cluster + External Secrets
# Operator (ESO) + the in-cluster objects.
#
# One `terraform apply` builds the cluster, its OIDC provider, a managed node
# group, KMS envelope encryption, the IRSA reader role, the ESO Helm release,
# and every in-cluster object (namespaces, service account, SecretStore,
# ExternalSecret, RBAC, sample app). One `terraform destroy` removes all of it.
#
# This env only READS the network environment's outputs (see network.tf); it
# never modifies the network or dev environments. It holds its own S3 state
# (distinct key) so the destroy runbook has a single authoritative state.
#
# NOTHING is created without an explicit `terraform apply`. EKS is chargeable
# (control plane ~$0.10/hr + a 2x t3.medium on-demand node group); review
# ../../../docs/costs.md first.

terraform {
  required_providers {
    aws        = { source = "hashicorp/aws", version = "~> 6.0" }
    kubernetes = { source = "hashicorp/kubernetes", version = "~> 2.31" }
    helm       = { source = "hashicorp/helm", version = "~> 2.13" }
    kubectl    = { source = "gavinbunney/kubectl", version = "~> 1.14" }
  }

  backend "s3" {
    bucket       = "dev-tech-state-bucket"                  # same bucket as dev
    key          = "secrets-rotation/eks/terraform.tfstate" # DISTINCT key — never collides with dev or network
    encrypt      = true
    region       = "us-east-1"
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "secrets-rotation-platform"
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = var.owner_tag
      Layer       = "eks"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  name_prefix = "${var.environment}-${var.app_name}"
  # Resource-level tags. Keep these distinct from the provider's default_tags
  # (Project/Environment/ManagedBy/Owner) — IAM compares tag keys
  # case-insensitively, so a lowercase "environment"/"owner" here would collide
  # with the capitalized default tags and fail CreateRole. Leave empty and let
  # default_tags provide the standard set.
  common_tags = {}
}

# ---- EKS cluster, node group, OIDC provider, KMS ----
module "eks" {
  source = "../../modules/eks"

  name_prefix        = local.name_prefix
  cluster_name       = "${local.name_prefix}-eks"
  cluster_version    = var.cluster_version
  private_subnet_ids = local.effective_private_subnet_ids

  node_instance_type = var.node_instance_type
  node_desired_size  = var.node_desired_size
  node_min_size      = var.node_min_size
  node_max_size      = var.node_max_size
  node_capacity_type = var.node_capacity_type

  cluster_endpoint_public_access = var.cluster_endpoint_public_access
  public_access_cidrs            = var.public_access_cidrs
  cluster_log_types              = var.cluster_log_types
  kms_key_arn                    = var.kms_key_arn

  tags = local.common_tags
}

# ---- IRSA reader role (needs the cluster OIDC provider) ----
module "eks_irsa" {
  source = "../../modules/eks-irsa"

  oidc_provider_arn = module.eks.oidc_provider_arn
  oidc_provider_url = module.eks.oidc_provider_url
  aws_region        = var.aws_region
  role_name         = "${local.name_prefix}-eso-reader"
  namespace         = var.app_namespace
  service_account   = var.service_account_name
  secret_prefix     = var.secret_prefix

  tags = local.common_tags
}

# ---- Provider auth from the cluster MODULE outputs (not data sources) ----
# The kubernetes/helm/kubectl providers are wired from the aws_eks_cluster
# resource outputs (endpoint + CA) exposed by module.eks, NOT from a separate
# data.aws_eks_cluster data source. A data source would try to read the cluster
# at plan time and fail with "couldn't find resource" when the cluster doesn't
# exist yet (first apply). Module outputs are deferred until the resource is
# created, so the single-apply model works.
#
# Auth uses the exec plugin (`aws eks get-token`) rather than
# data.aws_eks_cluster_auth, which also evaluates eagerly at plan time. The exec
# plugin defers token acquisition to when the provider actually makes an API
# call, after the cluster exists.
#
# On destroy, run while the cluster still exists (see README destroy runbook).

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_ca_data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.aws_region]
  }
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_ca_data)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.aws_region]
    }
  }
}

provider "kubectl" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_ca_data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.aws_region]
  }
  load_config_file = false
}

# ---- Namespaces (external-secrets + myapp), applied first ----
# Multi-doc file: use kubectl_file_documents, never hand-split on "---".
data "kubectl_file_documents" "namespaces" {
  content = file(var.manifest_namespaces)
}

resource "kubectl_manifest" "namespaces" {
  for_each  = data.kubectl_file_documents.namespaces.manifests
  yaml_body = each.value

  depends_on = [module.eks]
}

# ---- External Secrets Operator ----
resource "helm_release" "external_secrets" {
  name             = "external-secrets"
  repository       = "https://charts.external-secrets.io"
  chart            = "external-secrets"
  version          = var.eso_chart_version
  namespace        = var.eso_namespace
  create_namespace = true

  # create_namespace is a no-op when the external-secrets namespace already
  # exists from 00-namespace.yaml; Helm neither errors on nor deletes it.
  set {
    name  = "installCRDs"
    value = "true"
  }

  # Force the controller's AWS SDK to use the REGIONAL STS endpoint
  # (sts.us-east-1.amazonaws.com) instead of the global one
  # (sts.amazonaws.com). This keeps IRSA AssumeRoleWithWebIdentity on the
  # in-region endpoint, which is faster and avoids the occasional global-STS
  # resolution hiccup. Injected on the MAIN controller (chart `extraEnv` list),
  # which is the component that validates SecretStores and calls
  # GetSecretValue. The webhook/certController do not make STS calls, so they
  # are intentionally left untouched.
  set {
    name  = "extraEnv[0].name"
    value = "AWS_STS_REGIONAL_ENDPOINTS"
  }
  set {
    name  = "extraEnv[0].value"
    value = "regional"
  }
  set {
    name  = "extraEnv[1].name"
    value = "AWS_REGION"
  }
  set {
    name  = "extraEnv[1].value"
    value = "us-east-1"
  }

  # ESO pulls its default public chart images directly from the public registry
  # (oci.external-secrets.io). The VPC now has a NAT gateway, so the cluster
  # nodes have normal public egress — no private ECR mirror / image overrides
  # are needed. Leaving image.repository at the chart default keeps ESO on its
  # upstream images for the pinned chart version.

  timeout = var.eso_timeout

  depends_on = [module.eks, kubectl_manifest.namespaces]
}

# ---- Service account (the ONE manifest reconstructed in HCL) ----
# Reconstructs 10-serviceaccount-irsa.yaml so the real IRSA role ARN replaces
# the <ACCOUNT_ID> placeholder. Name/namespace/labels match the canonical YAML.
resource "kubernetes_service_account_v1" "myapp_secrets" {
  metadata {
    name      = var.service_account_name
    namespace = var.app_namespace
    labels = {
      "app.kubernetes.io/part-of" = "secrets-rotation-platform"
    }
    annotations = {
      "eks.amazonaws.com/role-arn" = module.eks_irsa.reader_role_arn
    }
  }

  depends_on = [kubectl_manifest.namespaces]
}

# ---- RBAC (least-privilege Role + RoleBinding), multi-doc ----
data "kubectl_file_documents" "rbac" {
  content = file(var.manifest_rbac)
}

resource "kubectl_manifest" "rbac" {
  for_each  = data.kubectl_file_documents.rbac.manifests
  yaml_body = each.value

  depends_on = [kubectl_manifest.namespaces]
}

# ---- SecretStore (CRD from ESO; also needs the service account) ----
resource "kubectl_manifest" "secretstore" {
  yaml_body = file(var.manifest_secretstore)

  depends_on = [
    helm_release.external_secrets,
    kubernetes_service_account_v1.myapp_secrets,
  ]
}

# ---- ExternalSecret (needs the SecretStore CRD/resource) ----
resource "kubectl_manifest" "externalsecret" {
  yaml_body = file(var.manifest_externalsecret)

  depends_on = [kubectl_manifest.secretstore]
}

# ---- Sample app ----
# The myapp-database Secret is written by ESO's reconcile loop (not Terraform),
# so the pod becomes Ready only after the first reconcile — a runtime event, not
# an apply-completion guarantee. The depends_on only tightens submission order.
resource "kubectl_manifest" "sample_app" {
  yaml_body = file(var.manifest_sample_app)

  depends_on = [
    kubernetes_service_account_v1.myapp_secrets,
    kubectl_manifest.externalsecret,
  ]
}
