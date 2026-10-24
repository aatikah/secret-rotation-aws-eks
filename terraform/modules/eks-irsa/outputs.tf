output "reader_role_arn" {
  value       = aws_iam_role.reader.arn
  description = "ARN of the ESO reader role, for the service account annotation."
}
