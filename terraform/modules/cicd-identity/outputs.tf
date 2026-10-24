output "deploy_role_arn" {
  value       = aws_iam_role.deploy.arn
  description = "ARN of the CI/CD deploy role to assume via OIDC."
}

output "oidc_provider_arn" {
  value       = local.provider_arn
  description = "ARN of the GitHub OIDC provider in use."
}
