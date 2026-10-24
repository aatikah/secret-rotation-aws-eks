output "rotation_role_arn" {
  description = "ARN of the rotation Lambda execution role."
  value       = aws_iam_role.rotation.arn
}

output "rotation_role_name" {
  description = "Name of the rotation Lambda execution role."
  value       = aws_iam_role.rotation.name
}
