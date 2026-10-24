# Network module: the VPC the rotation Lambda, RDS, and EKS worker nodes run in.
#
# Design for secrets rotation specifically:
#
# * The rotation Lambda runs in PRIVATE subnets so it can reach RDS privately.
#   A Lambda in a private subnet still needs to call the Secrets Manager API and
#   write to CloudWatch Logs. The private subnets now egress through a single
#   NAT gateway, so the Lambda reaches those public AWS APIs over NAT — no
#   interface VPC endpoints required.
#
# * The same private subnets also host the EKS managed node group. With NAT
#   egress the worker nodes reach public AWS APIs (ECR, STS, EC2) and public
#   container registries directly to bootstrap and pull images — they no longer
#   depend on interface VPC endpoints to join the cluster.
#
# * A single NAT gateway (var.enable_nat, now the default) lives in one public
#   subnet behind an internet gateway and provides general internet egress for
#   the private subnets via a 0.0.0.0/0 route on the private route table.
#
# * RDS is never public — it stays in the private subnets with no inbound route
#   from the internet gateway.
#
# Cost note: the single NAT gateway bills ~$32/month + per-GB egress; the S3
# gateway endpoint (kept for cheap ECR layer pulls) is free. See docs/costs.md.

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

data "aws_region" "current" {}

locals {
  az_count = length(var.availability_zones)
  # Carve /20 private subnets and /24 public subnets out of the VPC CIDR.
  private_cidrs = [for i in range(local.az_count) : cidrsubnet(var.vpc_cidr, 4, i)]
  public_cidrs  = [for i in range(local.az_count) : cidrsubnet(var.vpc_cidr, 8, i + 200)]
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(var.tags, { Name = "${var.name_prefix}-vpc" })
}

# ---- Private subnets (Lambda + RDS) ----
resource "aws_subnet" "private" {
  count             = local.az_count
  vpc_id            = aws_vpc.this.id
  cidr_block        = local.private_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]
  tags = merge(var.tags, {
    Name = "${var.name_prefix}-private-${var.availability_zones[count.index]}"
    Tier = "private"
  })
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  tags   = merge(var.tags, { Name = "${var.name_prefix}-private-rt" })
}

resource "aws_route_table_association" "private" {
  count          = local.az_count
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# ---- Optional public subnets + IGW + NAT (only when enable_nat = true) ----
resource "aws_internet_gateway" "this" {
  count  = var.enable_nat ? 1 : 0
  vpc_id = aws_vpc.this.id
  tags   = merge(var.tags, { Name = "${var.name_prefix}-igw" })
}

resource "aws_subnet" "public" {
  count                   = var.enable_nat ? local.az_count : 0
  vpc_id                  = aws_vpc.this.id
  cidr_block              = local.public_cidrs[count.index]
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true
  tags = merge(var.tags, {
    Name = "${var.name_prefix}-public-${var.availability_zones[count.index]}"
    Tier = "public"
  })
}

resource "aws_route_table" "public" {
  count  = var.enable_nat ? 1 : 0
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this[0].id
  }
  tags = merge(var.tags, { Name = "${var.name_prefix}-public-rt" })
}

resource "aws_route_table_association" "public" {
  count          = var.enable_nat ? local.az_count : 0
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}

resource "aws_eip" "nat" {
  count  = var.enable_nat ? 1 : 0
  domain = "vpc"
  tags   = merge(var.tags, { Name = "${var.name_prefix}-nat-eip" })
}

resource "aws_nat_gateway" "this" {
  count         = var.enable_nat ? 1 : 0
  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id
  tags          = merge(var.tags, { Name = "${var.name_prefix}-nat" })
  depends_on    = [aws_internet_gateway.this]
}

resource "aws_route" "private_nat" {
  count                  = var.enable_nat ? 1 : 0
  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[0].id
}

# Gateway endpoint for S3: ECR stores image layers in S3, so nodes must reach S3
# to pull images. Gateway endpoints are free and attach to a route table (no SG,
# no private DNS).
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
  tags              = merge(var.tags, { Name = "${var.name_prefix}-vpce-s3" })
}
