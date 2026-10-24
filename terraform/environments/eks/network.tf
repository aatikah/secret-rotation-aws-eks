# Network wiring for the eks environment.
#
# The eks env only READS the network environment's outputs — it never modifies
# the network or dev environments. Two ways to supply the VPC + private subnets
# the cluster and node group attach to:
#
#   A. Read the network environment's state (default). Set
#      use_network_remote_state = true and point network_state_* at where the
#      network environment stored its state. This reads vpc_id /
#      private_subnet_ids automatically.
#
#   B. Bring your own VPC. Set use_network_remote_state = false and supply
#      vpc_id and private_subnet_ids explicitly in terraform.tfvars.
#
# IMPORTANT — defaults diverge from dev. The CODE here mirrors
# environments/dev/network.tf, but the variable DEFAULTS differ on purpose: the
# eks env defaults network_state_backend to "s3" (dev defaults to "local").
# If the network env was actually applied with local state, set
# network_state_backend = "local" and
# network_state_config = { path = "../network/terraform.tfstate" } — otherwise
# the remote-state read points at an S3 object that may be empty or stale.

data "terraform_remote_state" "network" {
  count = var.use_network_remote_state ? 1 : 0

  backend = var.network_state_backend

  # For backend = "s3":    config = { bucket, key, region }
  # For backend = "local": config = { path = "../network/terraform.tfstate" }
  config = var.network_state_config
}

locals {
  net = var.use_network_remote_state ? data.terraform_remote_state.network[0].outputs : null

  effective_vpc_id = var.use_network_remote_state ? local.net.vpc_id : var.vpc_id
  effective_private_subnet_ids = (
    var.use_network_remote_state ? local.net.private_subnet_ids : var.private_subnet_ids
  )
}
