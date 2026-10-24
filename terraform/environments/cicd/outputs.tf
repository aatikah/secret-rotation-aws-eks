output "deploy_role_arn" {
  value       = module.cicd_identity.deploy_role_arn
  description = "Put this in the GitHub repo secret AWS_DEPLOY_ROLE_ARN."
}

output "oidc_provider_arn" {
  value       = module.cicd_identity.oidc_provider_arn
  description = "ARN of the GitHub OIDC provider the deploy role trusts."
}

output "github_setup_hint" {
  value       = <<-EOT
    GitHub repo configuration:
      1. Settings > Secrets and variables > Actions > Secrets:
         AWS_DEPLOY_ROLE_ARN = ${module.cicd_identity.deploy_role_arn}
      2. Settings > Secrets and variables > Actions > Variables:
         AWS_REGION = ${var.aws_region}
      3. Settings > Environments: create 'dev' with required reviewers.
    Then run the 'deploy_dev' workflow_dispatch from a ref in: ${join(", ", var.allowed_refs)}
  EOT
  description = "Copy-paste checklist for wiring GitHub to this role."
}
