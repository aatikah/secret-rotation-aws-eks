variable "aws_region" {
  type    = string
  default = "us-east-1"
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

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "availability_zones" {
  type        = list(string)
  description = "At least two AZs in your region (e.g. ['us-east-1a','us-east-1b'])."
  default     = ["us-east-1a", "us-east-1b"]
}

variable "enable_nat" {
  type        = bool
  description = "Create a single NAT gateway providing general egress for the private subnets (default path for the Lambda and EKS nodes). ~$32/month."
  default     = true
}
