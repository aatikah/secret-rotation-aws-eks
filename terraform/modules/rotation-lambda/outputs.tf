output "function_arn" {
  value       = aws_lambda_function.rotation.arn
  description = "ARN of the rotation Lambda function."
}

output "function_name" {
  value       = aws_lambda_function.rotation.function_name
  description = "Name of the rotation Lambda function."
}
