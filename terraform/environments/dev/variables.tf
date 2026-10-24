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

variable "rotation_interval_days" {
  type    = number
  default = 30
}

variable "log_level" {
  type    = string
  default = "INFO"
}

variable "log_retention_days" {
  type    = number
  default = 90
}

variable "python_runtime" {
  type    = string
  default = "python3.12"
}

variable "lambda_package_dir" {
  type        = string
  description = "Path to the built Lambda package dir (output of scripts/build_lambda.py)."
  default     = "../../modules/rotation-lambda/build/package"
}

variable "alarm_sns_topic_arns" {
  type    = list(string)
  default = []
}

# ---- Database (RDS) toggle + networking ----
variable "create_database" {
  type        = bool
  description = "Create a chargeable RDS PostgreSQL instance. true for a full deploy; false to run the secrets/Lambda/monitoring layer against an existing database."
  default     = true
}

# --- Networking source A: read the network bootstrap environment's state ---
variable "use_network_remote_state" {
  type        = bool
  description = "Read vpc_id/private_subnet_ids from the network environment's state instead of the explicit vars below."
  default     = true
}

variable "network_state_backend" {
  type        = string
  description = "Backend type of the network environment's state: 'local' or 's3'."
  # Default to S3 so CI (which has no gitignored terraform.tfvars) reads the
  # network layer's state from the same place the network env writes it. For a
  # local-state workflow, override to "local" in terraform.tfvars.
  default = "s3"
}

variable "network_state_config" {
  type        = map(string)
  description = "Backend config for the network state. local: { path = \"../network/terraform.tfstate\" }. s3: { bucket, key, region }."
  # Must match the backend block in environments/network/main.tf. Overridable
  # in terraform.tfvars (e.g. { path = \"../network/terraform.tfstate\" } for local).
  default = {
    bucket = "dev-tech-state-bucket-net"
    key    = "secrets-rotation/network/terraform.tfstate"
    region = "us-east-1"
  }
}

# --- Networking source B: bring your own VPC (used when use_network_remote_state = false) ---
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

variable "vpc_cidr" {
  type        = string
  description = "VPC CIDR, used to scope the Lambda's HTTPS egress to the interface VPC endpoints. Used only when use_network_remote_state = false."
  default     = ""
}

variable "db_host" {
  type        = string
  description = "Database endpoint written into the secret. Used only when create_database = false (an existing DB). When create_database = true the RDS endpoint is wired automatically."
  default     = ""
}

variable "db_port" {
  type    = number
  default = 5432
}

variable "db_name" {
  type    = string
  default = "appdb"
}
