output "cluster_name" {
  value       = module.eks.cluster_name
  description = "EKS cluster name (use with: aws eks update-kubeconfig --name <this> --region us-east-1)."
}

output "cluster_endpoint" {
  value       = module.eks.cluster_endpoint
  description = "Kubernetes API server endpoint."
}

output "oidc_provider_arn" {
  value       = module.eks.oidc_provider_arn
  description = "ARN of the cluster IAM OIDC provider."
}

output "reader_role_arn" {
  value       = module.eks_irsa.reader_role_arn
  description = "ARN of the ESO reader role annotated on the myapp-secrets service account."
}

output "kms_key_arn" {
  value       = module.eks.kms_key_arn
  description = "KMS key ARN used for secrets envelope encryption."
}
