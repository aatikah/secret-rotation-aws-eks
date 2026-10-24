variable "name_prefix" {
  type        = string
  description = "Prefix for monitoring resource names."
}

variable "function_name" {
  type        = string
  description = "Rotation Lambda function name (drives the log group name)."
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention. Keep bounded to control cost and exposure."
  default     = 90
}

variable "metric_namespace" {
  type        = string
  description = "CloudWatch namespace for custom rotation metrics."
  default     = "SecretsRotation"
}

variable "database_secret_name" {
  type        = string
  description = "Secret name used as the dimension for the staleness alarm."
}

variable "rotation_interval_days" {
  type        = number
  description = "Configured rotation interval, used for the staleness threshold."
  default     = 30
}

variable "staleness_grace_days" {
  type        = number
  description = "Extra days beyond the interval before the staleness alarm fires."
  default     = 2
}

variable "enable_staleness_alarm" {
  type        = bool
  description = "Whether to create the DaysSinceLastRotation alarm."
  default     = true
}

variable "alarm_sns_topic_arns" {
  type        = list(string)
  description = "SNS topic ARNs to notify on alarm (empty = no notification)."
  default     = []
}

variable "tags" {
  type        = map(string)
  description = "Tags for monitoring resources."
  default     = {}
}
