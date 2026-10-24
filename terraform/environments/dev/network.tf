# Network wiring for the dev environment.
#
# Three ways to supply the VPC + private subnets the Lambda and RDS need:
#
#   A. Use the network bootstrap environment (recommended). Set
#      use_network_remote_state = true and point network_state_* at where the
#      network environment stored its state. This reads vpc_id /
#      private_subnet_ids automatically — no copy-paste.
#
#   B. Bring your own VPC. Leave use_network_remote_state = false and set vpc_id
#      and private_subnet_ids explicitly in terraform.tfvars.
#
#   C. No database (create_database = false). Networking is unused.
#
# The locals below resolve the effective VPC/subnets from whichever source is
# selected, and the rest of the dev config (main.tf) reads these locals.

data "terraform_remote_state" "network" {
  count = var.use_network_remote_state ? 1 : 0

  backend = var.network_state_backend

  # For backend = "local": config = { path = "../network/terraform.tfstate" }
  # For backend = "s3":    config = { bucket, key, region }
  config = var.network_state_config
}

locals {
  net = var.use_network_remote_state ? data.terraform_remote_state.network[0].outputs : null

  effective_vpc_id = var.use_network_remote_state ? local.net.vpc_id : var.vpc_id
  effective_private_subnet_ids = (
    var.use_network_remote_state ? local.net.private_subnet_ids : var.private_subnet_ids
  )

  # VPC CIDR used to scope the Lambda's HTTPS egress to the interface VPC
  # endpoints. From the network state when available; otherwise fall back to
  # var.vpc_cidr (used in the bring-your-own-VPC path).
  vpc_cidr = var.use_network_remote_state ? local.net.vpc_cidr : var.vpc_cidr
}
