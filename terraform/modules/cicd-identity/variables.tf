variable "name_prefix" {
  type        = string
  description = "Prefix for CI/CD IAM resource names."
}

variable "github_org" {
  type        = string
  description = "GitHub organisation or user that owns the repo."
}

variable "github_repo" {
  type        = string
  description = "GitHub repository name."
}

# ---- Immutable GitHub numeric IDs (rename-proof trust anchor) ----
# GitHub's OIDC token can carry immutable unique IDs: the owner's account ID and
# the repository's ID. Unlike the org/repo *names* (which change on rename and
# can be reused by a different repo), these numeric IDs are permanent and never
# reused. Matching on them makes the trust policy immune to rename/hijack.
#
# Find them from a workflow's OIDC token (the `sub` becomes
# `repo:<org>@<ownerId>/<repo>@<repoId>:...`) or via the GitHub API:
#   owner id: GET https://api.github.com/users/<org>        -> .id
#   repo id : GET https://api.github.com/repos/<org>/<repo> -> .id
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
  description = "Git refs allowed to assume the role, e.g. ['refs/heads/main']."
  default     = ["refs/heads/main"]
}

variable "create_oidc_provider" {
  type        = bool
  description = "Create the GitHub OIDC provider (false reuses an existing one)."
  default     = true
}

variable "existing_oidc_provider_arn" {
  type        = string
  description = "ARN of an existing GitHub OIDC provider (when not creating one)."
  default     = ""
}

variable "oidc_thumbprints" {
  type        = list(string)
  description = "OIDC provider certificate thumbprints."
  # GitHub's root CA thumbprint. Verify against GitHub docs before apply.
  default = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

variable "deploy_policy_json" {
  type        = string
  description = "JSON IAM policy document scoping what CI may deploy (least privilege)."
}

variable "tags" {
  type        = map(string)
  description = "Tags for CI/CD IAM resources."
  default     = {}
}
