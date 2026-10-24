variable "name_prefix" {
  description = "Prefix for IAM resource names, e.g. 'dev-myapp'."
  type        = string
}

variable "rotatable_secret_arns" {
  description = "ARNs of secrets the rotation Lambda may rotate (read/write/stage)."
  type        = list(string)
}

variable "master_secret_arn" {
  description = "ARN of the master secret the rotation function reads to ALTER roles."
  type        = string
}

variable "log_group_arn" {
  description = "ARN of the rotation Lambda's CloudWatch log group."
  type        = string
}

variable "aws_region" {
  description = "AWS region (for log-group ARN scoping)."
  type        = string
}

variable "account_id" {
  description = "AWS account ID (for log-group ARN scoping)."
  type        = string
}

variable "vpc_access" {
  description = "Attach VPC access policy (needed when the Lambda runs in a VPC)."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags to apply to IAM resources."
  type        = map(string)
  default     = {}
}
