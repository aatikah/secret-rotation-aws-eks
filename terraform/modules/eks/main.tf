# EKS cluster module: control plane + managed node group + OIDC provider +
# KMS envelope encryption for Kubernetes Secrets at rest, plus the cluster and
# node IAM roles.
#
# This module takes the VPC's private subnet IDs as input and does NOT read any
# remote state, so it stays reusable and plan-testable in isolation. The
# environment composes it with the network remote-state read.

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
    # tls lives here because the OIDC provider thumbprint is read from the
    # cluster issuer's certificate via the tls_certificate data source below.
    tls = { source = "hashicorp/tls", version = "~> 4.0" }
  }
}

# ---- Cluster IAM role ----
data "aws_iam_policy_document" "cluster_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name               = "${var.name_prefix}-eks-cluster"
  assume_role_policy = data.aws_iam_policy_document.cluster_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "cluster_policy" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

# ---- Node IAM role ----
data "aws_iam_policy_document" "node_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name               = "${var.name_prefix}-eks-node"
  assume_role_policy = data.aws_iam_policy_document.node_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "node_worker" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

resource "aws_iam_role_policy_attachment" "node_ecr" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_role_policy_attachment" "node_cni" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
}

# ---- KMS key for secrets envelope encryption ----
# Created only when the caller does not pass an existing key. A short deletion
# window suits the disposable/cost-sensitive context so a destroyed key does
# not linger.
resource "aws_kms_key" "eks" {
  count                   = var.kms_key_arn == "" ? 1 : 0
  description             = "EKS secrets envelope encryption for ${var.cluster_name}"
  enable_key_rotation     = true
  deletion_window_in_days = 7
  tags                    = var.tags
}

resource "aws_kms_alias" "eks" {
  count         = var.kms_key_arn == "" ? 1 : 0
  name          = "alias/${var.name_prefix}-eks-secrets"
  target_key_id = aws_kms_key.eks[0].key_id
}

locals {
  effective_kms_key_arn = var.kms_key_arn == "" ? aws_kms_key.eks[0].arn : var.kms_key_arn
}

# ---- Cluster ----
resource "aws_eks_cluster" "this" {
  name     = var.cluster_name
  role_arn = aws_iam_role.cluster.arn
  version  = var.cluster_version

  vpc_config {
    subnet_ids              = var.private_subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = var.cluster_endpoint_public_access
    public_access_cidrs     = var.public_access_cidrs
  }

  encryption_config {
    resources = ["secrets"]
    provider {
      key_arn = local.effective_kms_key_arn
    }
  }

  enabled_cluster_log_types = var.cluster_log_types

  tags = var.tags

  # The cluster cannot be created before its role is authorized.
  depends_on = [aws_iam_role_policy_attachment.cluster_policy]
}

# ---- OIDC provider (required for IRSA) ----
data "tls_certificate" "oidc" {
  url = aws_eks_cluster.this.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "oidc" {
  url             = aws_eks_cluster.this.identity[0].oidc[0].issuer
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.oidc.certificates[0].sha1_fingerprint]
  tags            = var.tags
}

# ---- Managed node group ----
resource "aws_eks_node_group" "this" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "${var.name_prefix}-ng"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.private_subnet_ids

  capacity_type  = var.node_capacity_type
  instance_types = [var.node_instance_type]

  scaling_config {
    desired_size = var.node_desired_size
    min_size     = var.node_min_size
    max_size     = var.node_max_size
  }

  update_config {
    max_unavailable = 1
  }

  # Node role must be authorized before AWS tries to register nodes.
  depends_on = [
    aws_iam_role_policy_attachment.node_worker,
    aws_iam_role_policy_attachment.node_ecr,
    aws_iam_role_policy_attachment.node_cni,
  ]
}
