output "vpc_id" {
  value       = aws_vpc.this.id
  description = "ID of the VPC."
}

output "vpc_cidr" {
  value       = aws_vpc.this.cidr_block
  description = "CIDR block of the VPC."
}

output "private_subnet_ids" {
  value       = aws_subnet.private[*].id
  description = "Private subnet IDs (Lambda + RDS)."
}

output "public_subnet_ids" {
  value       = aws_subnet.public[*].id
  description = "Public subnet IDs (empty unless enable_nat = true)."
}

output "s3_gateway_endpoint_id" {
  value       = aws_vpc_endpoint.s3.id
  description = "S3 gateway VPC endpoint ID (used by EKS nodes to pull ECR image layers)."
}
