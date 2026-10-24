variable "oidc_provider_arn" {
  type        = string
  description = "ARN of the cluster's IAM OIDC provider (from modules/eks)."
}

variable "oidc_provider_url" {
  type        = string
  description = "Cluster OIDC issuer URL with https:// stripped (from modules/eks), used to build the IAM condition keys."
}

variable "aws_region" {
  type        = string
  description = "Region used to scope the Secrets Manager resource ARN. Single-sourced here so the ARN cannot drift from the rest of the stack."
}

variable "role_name" {
  type        = string
  description = "Name of the reader role (e.g. dev-myapp-eso-reader)."
}

variable "namespace" {
  type        = string
  description = "Kubernetes namespace of the service account that may assume the role."
  default     = "myapp"
}

variable "service_account" {
  type        = string
  description = "Service account name that may assume the role."
  default     = "myapp-secrets"
}

variable "secret_prefix" {
  type        = string
  description = "Secrets Manager name prefix the role may read. Must end in '*' to cover the ARN suffix Secrets Manager appends."
  default     = "dev/myapp/*"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags. Pass {} from the environment so provider default_tags supply the standard set (avoids the IAM duplicate-tag-key pitfall)."
  default     = {}
}
