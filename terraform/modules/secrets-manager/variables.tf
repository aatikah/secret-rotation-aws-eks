variable "environment" {
  type        = string
  description = "Environment namespace (dev | prod)."
}

variable "app_name" {
  type        = string
  description = "Application name used in the secret naming convention."
}

variable "db_host" {
  type        = string
  description = "Database host the credentials target."
}

variable "db_port" {
  type        = number
  description = "Database port."
  default     = 5432
}

variable "db_name" {
  type        = string
  description = "Database name."
  default     = "appdb"
}

variable "db_master_username" {
  type        = string
  description = "Master/admin DB username used by rotation to ALTER roles."
  default     = "postgres"
}

variable "db_master_password" {
  type        = string
  description = "Master/admin DB password. Supplied by the environment so the master secret and RDS share one source of truth."
  sensitive   = true
}

variable "api_provider" {
  type        = string
  description = "Identifier of the external API provider (metadata only)."
  default     = "mock"
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to all secrets (metadata only — never credentials)."
  default     = {}
}
