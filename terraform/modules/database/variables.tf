variable "create" {
  type        = bool
  description = "Whether to create the RDS instance. False skips the whole module."
  default     = false
}

variable "name_prefix" {
  type        = string
  description = "Prefix for database resource names."
}

variable "vpc_id" {
  type        = string
  description = "VPC the database lives in."
  default     = ""
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnet IDs for the DB subnet group (no public route)."
  default     = []
}

variable "lambda_security_group_id" {
  type        = string
  description = "Security group of the rotation Lambda, allowed to reach PostgreSQL."
  default     = ""
}

variable "engine_version" {
  type        = string
  description = "PostgreSQL engine version."
  default     = "18.3"
}

variable "instance_class" {
  type        = string
  description = "RDS instance class (smallest sensible default for a disposable test DB)."
  default     = "db.t4g.micro"
}

variable "db_name" {
  type        = string
  description = "Initial database name."
  default     = "appdb"
}

variable "master_username" {
  type        = string
  description = "Master username for the instance."
  default     = "postgres"
}

variable "master_password" {
  type        = string
  description = "Master password for the instance. Supplied by the environment so the master secret and RDS share one source of truth."
  sensitive   = true
}

variable "tags" {
  type        = map(string)
  description = "Tags for database resources."
  default     = {}
}
