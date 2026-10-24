output "database_secret_arn" {
  value       = aws_secretsmanager_secret.database.arn
  description = "ARN of the application database secret."
}

output "master_secret_arn" {
  value       = aws_secretsmanager_secret.master.arn
  description = "ARN of the master secret."
}

output "api_secret_arn" {
  value       = aws_secretsmanager_secret.api.arn
  description = "ARN of the external-API secret."
}

output "rotatable_secret_arns" {
  value       = [aws_secretsmanager_secret.database.arn]
  description = "Secrets the rotation Lambda is permitted to rotate."
}
