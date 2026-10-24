variable "aws_region" {
  type        = string
  description = "Region for the deploy role's scoped ARNs. Must match the AWS_REGION GitHub variable and the dev env region."
  default     = "us-east-1"
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

# ---- GitHub repository the deploy role trusts (REQUIRED — no safe default) ----
variable "github_org" {
  type        = string
  description = "GitHub organisation or user that owns the repo (e.g. 'your-github-username')."
}

variable "github_repo" {
  type        = string
  description = "GitHub repository name (e.g. 'aws-secrets-rotation-platform')."
}

# ---- Immutable GitHub numeric IDs (REQUIRED — rename-proof trust anchor) ----
# This repo uses GitHub's immutable unique IDs, so the OIDC token subject is
# `repo:<org>@<ownerId>/<repo>@<repoId>:...`. Supply the two numeric IDs below.
# Read them from a deploy-dev run's OIDC subject, or from the GitHub API:
#   owner id: curl -s https://api.github.com/users/<org>        | jq .id
#   repo id : curl -s https://api.github.com/repos/<org>/<repo> | jq .id
variable "github_owner_id" {
  type        = string
  description = "Immutable numeric account ID of the GitHub org/user (repository_owner_id claim)."
}

variable "github_repo_id" {
  type        = string
  description = "Immutable numeric repository ID (repository_id claim)."
}

variable "allowed_refs" {
  type        = list(string)
  description = "Git refs allowed to assume the deploy role. deploy-dev runs on workflow_dispatch, so include the branch you dispatch from."
  default     = ["refs/heads/main"]
}

# ---- OIDC provider: create a new one, or reuse an account-wide existing one ----
# An AWS account can have only ONE GitHub Actions OIDC provider
# (token.actions.githubusercontent.com). If your account already has one (from
# another project), set create_oidc_provider = false and pass its ARN below,
# or `terraform apply` will fail with EntityAlreadyExists.
variable "create_oidc_provider" {
  type        = bool
  description = "Create the GitHub OIDC provider. Set false to reuse an existing one in the account."
  default     = true
}

variable "existing_oidc_provider_arn" {
  type        = string
  description = "ARN of an existing GitHub OIDC provider (only when create_oidc_provider = false)."
  default     = ""
}

# ---- State buckets the deploy role may read/write (for the least-privilege S3 policy) ----
variable "dev_state_bucket" {
  type        = string
  description = "S3 bucket holding the dev env Terraform state (CI reads+writes secrets-rotation/dev/*). Matches the dev backend bucket."
  default     = "dev-tech-state-bucket"
}

variable "network_state_bucket" {
  type        = string
  description = "S3 bucket holding the network env Terraform state (CI reads it via remote_state). Matches the network backend bucket."
  default     = "dev-tech-state-bucket-net"
}
