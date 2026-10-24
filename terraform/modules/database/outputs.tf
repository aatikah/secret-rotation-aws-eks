output "endpoint" {
  value       = var.create ? aws_db_instance.this[0].address : null
  description = "Database host endpoint (null when the module is disabled)."
}

output "port" {
  value       = var.create ? aws_db_instance.this[0].port : null
  description = "Database port."
}

output "security_group_id" {
  value       = var.create ? aws_security_group.db[0].id : null
  description = "Database security group ID."
}
