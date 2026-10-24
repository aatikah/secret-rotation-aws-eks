variable "name_prefix" {
  type        = string
  description = "Resource name prefix, e.g. dev-myapp."
}

variable "cluster_name" {
  type        = string
  description = "EKS cluster name, e.g. dev-myapp-eks."
}

variable "cluster_version" {
  type        = string
  description = "EKS control-plane version."
  default     = "1.31"
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnet IDs the cluster and node group attach to."
}

variable "node_instance_type" {
  type        = string
  description = "Managed node group instance type. Drop to t3.small for a cheaper single-node setup."
  default     = "t3.medium"
}

variable "node_desired_size" {
  type        = number
  description = "Desired number of nodes."
  default     = 2
}

variable "node_min_size" {
  type        = number
  description = "Minimum number of nodes."
  default     = 1
}

variable "node_max_size" {
  type        = number
  description = "Maximum number of nodes."
  default     = 3
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

variable "cluster_endpoint_public_access" {
  type        = bool
  description = "Expose the Kubernetes API endpoint publicly so the operator can run terraform from a workstation. Tightening point."
  default     = true
}

variable "public_access_cidrs" {
  type        = list(string)
  description = "CIDRs allowed to reach the public API endpoint. Tighten from 0.0.0.0/0 in a locked-down setup."
  default     = ["0.0.0.0/0"]
}

variable "cluster_log_types" {
  type        = list(string)
  description = "Control-plane log types sent to CloudWatch (log group /aws/eks/<cluster>/cluster)."
  default     = ["api", "audit", "authenticator"]
}

variable "kms_key_arn" {
  type        = string
  description = "Existing KMS key ARN for secrets envelope encryption. Empty creates a dedicated key in this module."
  default     = ""
}

variable "tags" {
  type        = map(string)
  description = "Resource tags. Pass {} from the environment so provider default_tags supply the standard set."
  default     = {}
}
