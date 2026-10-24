variable "name_prefix" {
  type        = string
  description = "Prefix for the function name, e.g. 'dev-myapp'."
}

variable "role_arn" {
  type        = string
  description = "Execution role ARN for the Lambda."
}

variable "package_source_dir" {
  type        = string
  description = "Directory containing the built Lambda package (handler + deps)."
}

variable "python_runtime" {
  type        = string
  description = "Lambda Python runtime."
  default     = "python3.12"
}

variable "timeout_seconds" {
  type        = number
  description = "Function timeout. Must exceed the slowest DB connect + ALTER."
  default     = 30
}

variable "memory_mb" {
  type        = number
  description = "Function memory."
  default     = 256
}

variable "log_level" {
  type        = string
  description = "LOG_LEVEL env var for the function."
  default     = "INFO"
}

variable "aws_region" {
  type        = string
  description = "Region env var for boto3."
}

variable "account_id" {
  type        = string
  description = "AWS account ID (for the invoke permission source_account)."
}

variable "database_secret_arn" {
  type        = string
  description = "ARN of the secret this function rotates. Retained for documentation/wiring; the invoke permission is scoped by source_account, not this ARN (see main.tf)."
  default     = ""
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private subnet IDs when the Lambda must reach a VPC database. Empty = no VPC."
  default     = []
}

variable "security_group_ids" {
  type        = list(string)
  description = "Security group IDs for the Lambda ENIs when in a VPC."
  default     = []
}

variable "tags" {
  type        = map(string)
  description = "Tags for the function."
  default     = {}
}
