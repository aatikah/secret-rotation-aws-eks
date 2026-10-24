# Network bootstrap environment.
#
# Apply this FIRST — it creates the VPC, private subnets, a single NAT gateway
# for egress, and the free S3 gateway endpoint the rotation Lambda and RDS need.
# It has its own state so the network has an independent lifecycle: destroying
# the `dev` app does not tear down the VPC.
#
# The `dev` environment reads this environment's outputs automatically via a
# terraform_remote_state data source (see environments/dev/network.tf), so you
# do not hand-copy VPC/subnet IDs.
#
# Order of operations:
#   1. (cd environments/network) terraform init && terraform apply
#   2. (cd environments/dev)     terraform init && terraform apply
#
# Review docs/costs.md: the VPC and subnets are free; the single NAT gateway
# (enable_nat = true by default) is the main cost (~$32/month + per-GB egress).


terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Remote state (recommended so the dev env can read it from S3). For a solo
  # throwaway test you may use local state — the dev env's network.tf has a
  # matching local/remote switch.

  backend "s3" {
    bucket       = "dev-tech-state-bucket-net"
    key          = "secrets-rotation/network/terraform.tfstate"
    encrypt      = true
    region       = "us-east-1"
    use_lockfile = true
  }
}


provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "secrets-rotation-platform"
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = var.owner_tag
      Layer       = "network"
    }
  }
}

module "network" {
  source = "../../modules/network"

  name_prefix        = "${var.environment}-${var.app_name}"
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
  enable_nat         = var.enable_nat
  tags = {
    owner       = var.owner_tag
    environment = var.environment
  }
}
