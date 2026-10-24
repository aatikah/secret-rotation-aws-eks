variable "name_prefix" {
  type        = string
  description = "Prefix for network resource names, e.g. 'dev-myapp'."
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC."
  default     = "10.20.0.0/16"
}

variable "availability_zones" {
  type        = list(string)
  description = "AZs to spread private (and optional public) subnets across. Use at least two for RDS."

  validation {
    condition     = length(var.availability_zones) >= 2
    error_message = "provide at least two availability zones (RDS requires a subnet group spanning 2+ AZs)."
  }
}

variable "enable_nat" {
  type        = bool
  description = "Create public subnets + IGW + a single NAT gateway for general internet egress. This is the default egress path: the rotation Lambda and EKS worker nodes reach public AWS APIs and registries over NAT. The NAT gateway adds ~$32/month."
  default     = true
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to all network resources."
  default     = {}
}
