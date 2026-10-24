variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region. Pinned to us-east-1 (see validation)."
  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "This stack is us-east-1 only: the canonical SecretStore YAML hardcodes region us-east-1 and the Secrets Manager data lives in us-east-1."
  }
}

variable "environment" {
  type    = string
  default = "dev"
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be 'dev' or 'prod'."
  }
}

variable "app_name" {
  type    = string
  default = "myapp"
}

variable "owner_tag" {
  type    = string
  default = "team-platform"
}

# ---- Cluster ----
variable "cluster_version" {
  type        = string
  description = "EKS control-plane version."
  default     = "1.31"
}

variable "cluster_endpoint_public_access" {
  type        = bool
  description = "Expose the Kubernetes API endpoint publicly so the operator can run terraform from a workstation."
  default     = true
}

variable "public_access_cidrs" {
  type        = list(string)
  description = "CIDRs allowed to reach the public API endpoint. Tightening point."
  default     = ["0.0.0.0/0"]
}

variable "cluster_log_types" {
  type        = list(string)
  description = "Control-plane log types sent to CloudWatch."
  default     = ["api", "audit", "authenticator"]
}

variable "kms_key_arn" {
  type        = string
  description = "Existing KMS key ARN for secrets envelope encryption. Empty creates a dedicated key."
  default     = ""
}

# ---- Managed node group ----
variable "node_instance_type" {
  type        = string
  description = "Node instance type. Drop to t3.small for a cheaper setup."
  default     = "t3.medium"
}

variable "node_desired_size" {
  type    = number
  default = 2
}

variable "node_min_size" {
  type    = number
  default = 1
}

variable "node_max_size" {
  type    = number
  default = 3
  validation {
    condition     = var.node_min_size >= 1 && var.node_min_size <= var.node_desired_size && var.node_desired_size <= var.node_max_size
    error_message = "Node sizing must satisfy 1 <= node_min_size <= node_desired_size <= node_max_size."
  }
}

variable "node_capacity_type" {
  type        = string
  description = "Node group capacity type: ON_DEMAND or SPOT."
  default     = "ON_DEMAND"
  validation {
    condition     = contains(["ON_DEMAND", "SPOT"], var.node_capacity_type)
    error_message = "node_capacity_type must be 'ON_DEMAND' or 'SPOT'."
  }
}

# ---- External Secrets Operator (ESO) ----
variable "eso_chart_version" {
  type        = string
  description = "ESO Helm chart version (docs' pin)."
  default     = "0.16.2"
}

variable "eso_namespace" {
  type    = string
  default = "external-secrets"
}

variable "eso_timeout" {
  type        = number
  description = "Helm release timeout in seconds. CRD install + operator rollout on a cold node group can exceed the 300s default."
  default     = 600
}

# ---- In-cluster identity ----
variable "app_namespace" {
  type    = string
  default = "myapp"
}

variable "service_account_name" {
  type    = string
  default = "myapp-secrets"
}

variable "secret_prefix" {
  type        = string
  description = "Secrets Manager read scope. Must end in '*' to cover the ARN suffix."
  default     = "dev/myapp/*"
}

# ---- Networking: source A — read the network environment's state ----
# NOTE: the defaults here DIVERGE from the dev environment on purpose. dev
# defaults to local state; the eks env defaults to S3 remote state because it
# is more likely to run from CI / a second workstation that does not have the
# network env's local state file on disk. See README.md ("Network-state
# divergence from dev").
variable "use_network_remote_state" {
  type        = bool
  description = "Read vpc_id/private_subnet_ids from the network environment's state instead of the explicit vars below."
  default     = true
}

variable "network_state_backend" {
  type        = string
  description = "Backend type of the network environment's state: 'local' or 's3'. DIVERGES from dev (which defaults to 'local')."
  default     = "s3"
}

variable "network_state_config" {
  type        = map(string)
  description = "Backend config for the network state. s3: { bucket, key, region }. local: { path = \"../network/terraform.tfstate\" }."
  default = {
    bucket = "dev-tech-state-bucket-net"
    key    = "secrets-rotation/network/terraform.tfstate"
    region = "us-east-1"
  }
}

# ---- Networking: source B — bring your own VPC ----
variable "vpc_id" {
  type        = string
  description = "Existing VPC ID. Used only when use_network_remote_state = false."
  default     = ""
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Existing private subnet IDs (2+ AZs). Used only when use_network_remote_state = false."
  default     = []
}

# ---- Canonical manifest paths (relative to this environment directory) ----
variable "manifest_namespaces" {
  type    = string
  default = "../../../kubernetes/external-secrets/00-namespace.yaml"
}

variable "manifest_secretstore" {
  type    = string
  default = "../../../kubernetes/external-secrets/20-secretstore.yaml"
}

variable "manifest_externalsecret" {
  type    = string
  default = "../../../kubernetes/external-secrets/30-externalsecret.yaml"
}

variable "manifest_rbac" {
  type    = string
  default = "../../../kubernetes/policies/rbac.yaml"
}

variable "manifest_sample_app" {
  type    = string
  default = "../../../kubernetes/sample-app/deployment.yaml"
}
