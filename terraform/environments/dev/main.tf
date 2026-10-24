# Dev environment composition.
#
# This wires the modules together for a disposable development deployment on AWS:
#   database (RDS) + secrets-manager + iam + monitoring + rotation-lambda.
#
# When create_database = true (the documented default for a full deploy), the
# secret's db_host is wired from the RDS endpoint automatically. Set it false
# only to deploy the secrets/Lambda/monitoring layer against an existing
# database (supply var.db_host) — that path skips RDS and its cost.
#
# Nothing here is applied without an explicit `terraform apply`.
# IMPORTANT: review docs/costs.md before `apply`.

terraform {
  # required_version = ">= 1.5.0, < 2.0.0"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 6.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.4" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
  }

  # Remote state with locking. Fill in your bucket/table and uncomment, OR run
  # locally for a throwaway dev test (state stays on your machine, gitignored).
  backend "s3" {
    bucket       = "dev-tech-state-bucket"
    key          = "secrets-rotation/dev/terraform.tfstate"
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
    }
  }
}

data "aws_caller_identity" "current" {}

# Single source of truth for the RDS master password. Generated once here and
# fed into BOTH the database module (as RDS's actual master password) and the
# secrets-manager module (as the master secret's stored password) so the two
# can never drift apart. The value lands only in Terraform state and Secrets
# Manager — never in config, tfvars, or logs (see docs/terraform-state.md).
resource "random_password" "db_master" {
  length           = 32
  special          = true
  override_special = "!#%*-_=+:?"
}

locals {
  name_prefix = "${var.environment}-${var.app_name}"
  # Resource-level tags. Keep these distinct from the provider's default_tags
  # (Project/Environment/ManagedBy/Owner) — IAM compares tag keys
  # case-insensitively, so a lowercase "environment"/"owner" here would collide
  # with the capitalized default tags and fail CreateRole. Leave empty and let
  # default_tags provide the standard set.
  common_tags = {}
  # When RDS is created here, point the secret at its endpoint automatically so
  # no two-phase apply or manual db_host is needed. Otherwise use var.db_host
  # (an existing database endpoint).
  effective_db_host = var.create_database ? module.database.endpoint : var.db_host
}

# ---- Secrets (db_host wired from RDS when enabled; rotation wired below) ----
module "secrets_manager" {
  source = "../../modules/secrets-manager"

  environment        = var.environment
  app_name           = var.app_name
  db_host            = local.effective_db_host
  db_port            = var.db_port
  db_name            = var.db_name
  db_master_password = random_password.db_master.result
  tags               = local.common_tags
}

# Automatic rotation wiring lives here so it can depend on both the secret and
# the Lambda without creating a module cycle.
resource "aws_secretsmanager_secret_rotation" "database" {
  secret_id           = module.secrets_manager.database_secret_arn
  rotation_lambda_arn = module.rotation_lambda.function_arn

  rotation_rules {
    automatically_after_days = var.rotation_interval_days
  }

  depends_on = [module.rotation_lambda]
}

# ---- Monitoring (log group created before the Lambda so IAM can scope to it) ----
module "monitoring" {
  source = "../../modules/monitoring"

  name_prefix            = local.name_prefix
  function_name          = "${local.name_prefix}-db-rotation"
  database_secret_name   = "${var.environment}/${var.app_name}/database"
  rotation_interval_days = var.rotation_interval_days
  log_retention_days     = var.log_retention_days
  alarm_sns_topic_arns   = var.alarm_sns_topic_arns
  tags                   = local.common_tags
}

# ---- IAM execution role for the rotation Lambda ----
module "iam" {
  source = "../../modules/iam"

  name_prefix           = local.name_prefix
  rotatable_secret_arns = module.secrets_manager.rotatable_secret_arns
  master_secret_arn     = module.secrets_manager.master_secret_arn
  log_group_arn         = module.monitoring.rotation_log_group_arn
  aws_region            = var.aws_region
  account_id            = data.aws_caller_identity.current.account_id
  vpc_access            = var.create_database
  tags                  = local.common_tags
}

# ---- Rotation Lambda ----
module "rotation_lambda" {
  source = "../../modules/rotation-lambda"

  name_prefix         = local.name_prefix
  role_arn            = module.iam.rotation_role_arn
  package_source_dir  = var.lambda_package_dir
  python_runtime      = var.python_runtime
  aws_region          = var.aws_region
  account_id          = data.aws_caller_identity.current.account_id
  database_secret_arn = module.secrets_manager.database_secret_arn
  log_level           = var.log_level
  subnet_ids          = var.create_database ? local.effective_private_subnet_ids : []
  security_group_ids  = var.create_database ? [aws_security_group.lambda[0].id] : []
  tags                = local.common_tags
}

# ---- Lambda security group (standalone, so the DB can admit it without a
#      module cycle). Created only when the Lambda runs in a VPC. ----
resource "aws_security_group" "lambda" {
  count       = var.create_database ? 1 : 0
  name        = "${local.name_prefix}-rotation-lambda-sg"
  description = "Egress for the rotation Lambda to reach RDS."
  vpc_id      = local.effective_vpc_id
  tags        = local.common_tags
}

resource "aws_security_group_rule" "lambda_egress_pg" {
  count             = var.create_database ? 1 : 0
  type              = "egress"
  from_port         = var.db_port
  to_port           = var.db_port
  protocol          = "tcp"
  security_group_id = aws_security_group.lambda[0].id
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "PostgreSQL egress to RDS."
}

# HTTPS egress so the Lambda can reach Secrets Manager and CloudWatch Logs.
# Without this the SG has no 443 egress (a custom SG drops the default
# allow-all egress), so every Secrets Manager API call made during a rotation
# step hangs until the Lambda's timeout. Open to 0.0.0.0/0 because the Lambda
# now reaches the AWS public APIs over the VPC's NAT gateway (the interface VPC
# endpoints were removed), matching the lambda_egress_pg pattern.
resource "aws_security_group_rule" "lambda_egress_https" {
  count             = var.create_database ? 1 : 0
  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  security_group_id = aws_security_group.lambda[0].id
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "HTTPS egress to Secrets Manager and Logs via NAT."
}

# ---- RDS PostgreSQL (private, non-public). Created when create_database=true ----
module "database" {
  source = "../../modules/database"

  create                   = var.create_database
  name_prefix              = local.name_prefix
  vpc_id                   = local.effective_vpc_id
  private_subnet_ids       = local.effective_private_subnet_ids
  lambda_security_group_id = var.create_database ? aws_security_group.lambda[0].id : ""
  db_name                  = var.db_name
  master_password          = random_password.db_master.result
  tags                     = local.common_tags
}
