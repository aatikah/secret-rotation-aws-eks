output "database_secret_arn" {
  value       = module.secrets_manager.database_secret_arn
  description = "ARN of the application database secret."
}

output "master_secret_arn" {
  value       = module.secrets_manager.master_secret_arn
  description = "ARN of the master secret."
}

output "api_secret_arn" {
  value       = module.secrets_manager.api_secret_arn
  description = "ARN of the external-API secret."
}

output "rotation_lambda_arn" {
  value       = module.rotation_lambda.function_arn
  description = "ARN of the rotation Lambda."
}

output "rotation_log_group" {
  value       = module.monitoring.rotation_log_group_name
  description = "CloudWatch log group for the rotation Lambda."
}

output "database_endpoint" {
  value       = module.database.endpoint
  description = "RDS endpoint (null when create_database = false)."
}
