output "vpc_id" {
  value       = module.network.vpc_id
  description = "VPC ID — consumed by the dev environment."
}

output "vpc_cidr" {
  value       = module.network.vpc_cidr
  description = "VPC CIDR."
}

output "private_subnet_ids" {
  value       = module.network.private_subnet_ids
  description = "Private subnet IDs for the Lambda + RDS — consumed by the dev environment."
}

output "public_subnet_ids" {
  value       = module.network.public_subnet_ids
  description = "Public subnet IDs (empty unless enable_nat = true)."
}

output "s3_gateway_endpoint_id" {
  value       = module.network.s3_gateway_endpoint_id
  description = "S3 gateway VPC endpoint ID (used by EKS nodes to pull ECR image layers)."
}
