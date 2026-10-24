output "rotation_log_group_name" {
  value       = aws_cloudwatch_log_group.rotation.name
  description = "Name of the rotation Lambda log group."
}

output "rotation_log_group_arn" {
  value       = aws_cloudwatch_log_group.rotation.arn
  description = "ARN of the rotation Lambda log group."
}
