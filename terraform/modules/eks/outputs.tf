output "cluster_name" {
  value       = aws_eks_cluster.this.name
  description = "EKS cluster name."
}

output "cluster_endpoint" {
  value       = aws_eks_cluster.this.endpoint
  description = "Kubernetes API server endpoint."
}

output "cluster_ca_data" {
  value       = aws_eks_cluster.this.certificate_authority[0].data
  description = "Base64-encoded cluster CA certificate."
}

output "oidc_provider_arn" {
  value       = aws_iam_openid_connect_provider.oidc.arn
  description = "ARN of the cluster IAM OIDC provider."
}

output "oidc_provider_url" {
  value       = replace(aws_eks_cluster.this.identity[0].oidc[0].issuer, "https://", "")
  description = "Cluster OIDC issuer URL with https:// stripped, for building IAM condition keys."
}

output "kms_key_arn" {
  value       = local.effective_kms_key_arn
  description = "KMS key ARN used for secrets envelope encryption."
}
