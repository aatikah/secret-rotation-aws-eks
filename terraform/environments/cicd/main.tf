# CI/CD identity bootstrap environment.
#
# Apply this ONCE, locally, before GitHub Actions can run the gated `deploy-dev`
# job. It creates the GitHub Actions OIDC provider (unless you reuse an existing
# one) and a narrowly-scoped IAM role that CI assumes via short-lived OIDC
# tokens — so NO long-lived AWS keys ever live in GitHub secrets.
#
# Why its own environment (separate state)?
#   * It matches the project's one-concern-per-environment layout (network, dev,
#     eks each have independent state).
#   * It avoids a bootstrap paradox: the deploy role cannot live in `dev`,
#     because `dev` is the very thing CI deploys USING this role. Keeping the
#     identity in its own state breaks that circularity.
#   * IAM identity (an account-wide OIDC provider + a deploy role) is more
#     sensitive than app resources; isolating it means `terraform destroy` of
#     `dev` can never delete the CI role, and vice versa.
#
# Order of operations (one time):
#   1. Create the S3 state buckets and apply `network`.
#   2. (cd environments/cicd) terraform init && terraform apply
#   3. Copy the `deploy_role_arn` output into the GitHub repo secret
#      AWS_DEPLOY_ROLE_ARN; set the repo variable AWS_REGION; create a `dev`
#      GitHub environment with required reviewers.
#   4. CI's `deploy-dev` job can now assume the role and apply the dev env.
#
# This environment is applied by a human with elevated (bootstrap) credentials —
# NOT by CI. CI only consumes its output.

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Dedicated state key so the CI identity has an independent lifecycle. Reuses
  # the same state bucket as the network env's backend; only the key differs.
  # For a solo throwaway test you may comment this out and use local state.
  backend "s3" {
    bucket       = "dev-tech-state-bucket-net"
    key          = "secrets-rotation/cicd/terraform.tfstate"
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
      Layer       = "cicd"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  name_prefix = "${var.environment}-${var.app_name}"

  # Least-privilege deploy policy: exactly what a `terraform apply` of the `dev`
  # environment needs, and nothing more. The dev apply manages Secrets Manager
  # secrets + rotation, the rotation Lambda, its IAM role, CloudWatch Logs +
  # alarms, RDS, and a Lambda security group; it also reads/writes its own
  # Terraform state in S3 (with the native S3 lock) and reads the network
  # remote state. Resources are scoped by name prefix / ARN where the AWS API
  # supports it; APIs that only allow "*" (most Describe* calls, and service
  # actions that do not support resource-level permissions) are listed
  # explicitly rather than granted via a broad managed policy.
  deploy_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # ---- Terraform state (S3 backend + native lock object) ----
      {
        Sid    = "TerraformStateBucketList"
        Effect = "Allow"
        Action = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = [
          "arn:aws:s3:::${var.dev_state_bucket}",
          "arn:aws:s3:::${var.network_state_bucket}",
        ]
      },
      {
        Sid    = "TerraformStateObjects"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = [
          # dev state (read+write) and its native lock object
          "arn:aws:s3:::${var.dev_state_bucket}/secrets-rotation/dev/*",
          # network state (read-only consumption via remote_state data source)
          "arn:aws:s3:::${var.network_state_bucket}/secrets-rotation/network/*",
        ]
      },
      # ---- Secrets Manager (the secrets + rotation config) ----
      {
        Sid    = "SecretsManager"
        Effect = "Allow"
        Action = [
          "secretsmanager:CreateSecret",
          "secretsmanager:DeleteSecret",
          "secretsmanager:DescribeSecret",
          "secretsmanager:GetSecretValue",
          "secretsmanager:PutSecretValue",
          "secretsmanager:TagResource",
          "secretsmanager:UntagResource",
          "secretsmanager:UpdateSecret",
          "secretsmanager:GetResourcePolicy",
          "secretsmanager:RotateSecret",
          "secretsmanager:CancelRotateSecret",
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.environment}/${var.app_name}/*"
      },
      # ---- Lambda (the rotation function) ----
      {
        Sid    = "Lambda"
        Effect = "Allow"
        Action = [
          "lambda:CreateFunction",
          "lambda:DeleteFunction",
          "lambda:GetFunction",
          "lambda:GetFunctionConfiguration",
          "lambda:GetFunctionCodeSigningConfig",
          "lambda:GetFunctionConcurrency",
          "lambda:GetRuntimeManagementConfig",
          "lambda:ListVersionsByFunction",
          "lambda:UpdateFunctionCode",
          "lambda:UpdateFunctionConfiguration",
          "lambda:AddPermission",
          "lambda:RemovePermission",
          "lambda:GetPolicy",
          "lambda:TagResource",
          "lambda:UntagResource",
          # Required by the Secrets Manager RotateSecret association preflight,
          # which invokes the rotation function AS THE CALLING PRINCIPAL (this
          # deploy role) — separate from the function's resource-based policy
          # that lets the secretsmanager.amazonaws.com service invoke it.
          # Without this, `terraform apply` of aws_secretsmanager_secret_rotation
          # fails from a clean slate with a misleading
          # "AccessDeniedException ... must have the permission lambda:InvokeFunction".
          "lambda:InvokeFunction",
        ]
        Resource = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${local.name_prefix}-db-rotation"
      },
      # ---- IAM for the rotation Lambda's execution role ----
      {
        Sid    = "IamRotationRole"
        Effect = "Allow"
        Action = [
          "iam:CreateRole",
          "iam:DeleteRole",
          "iam:GetRole",
          "iam:PassRole",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:PutRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:AttachRolePolicy",
          "iam:DetachRolePolicy",
        ]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.name_prefix}-*"
      },
      # ---- CloudWatch Logs + alarms (monitoring module) ----
      {
        Sid    = "CloudWatchLogsAndAlarms"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:DeleteLogGroup",
          "logs:DescribeLogGroups",
          "logs:PutRetentionPolicy",
          "logs:TagResource",
          "logs:UntagResource",
          "logs:ListTagsForResource",
          "logs:PutMetricFilter",
          "logs:DeleteMetricFilter",
          "logs:DescribeMetricFilters",
          "cloudwatch:PutMetricAlarm",
          "cloudwatch:DeleteAlarms",
          "cloudwatch:DescribeAlarms",
          "cloudwatch:ListTagsForResource",
          "cloudwatch:TagResource",
          "cloudwatch:UntagResource",
        ]
        Resource = "*"
      },
      # ---- RDS (the private PostgreSQL instance) ----
      {
        Sid    = "Rds"
        Effect = "Allow"
        Action = [
          "rds:CreateDBInstance",
          "rds:DeleteDBInstance",
          "rds:DescribeDBInstances",
          "rds:ModifyDBInstance",
          "rds:CreateDBSubnetGroup",
          "rds:DeleteDBSubnetGroup",
          "rds:DescribeDBSubnetGroups",
          "rds:AddTagsToResource",
          "rds:RemoveTagsFromResource",
          "rds:ListTagsForResource",
        ]
        Resource = "*"
      },
      # ---- EC2 / VPC (the Lambda security group; describes for data sources) ----
      # SG mutations and tagging support resource-level scoping poorly across the
      # create/describe lifecycle, so EC2 is granted at "*" but limited to the
      # specific describe + security-group actions the dev apply performs.
      {
        Sid    = "Ec2SecurityGroupAndDescribe"
        Effect = "Allow"
        Action = [
          "ec2:CreateSecurityGroup",
          "ec2:DeleteSecurityGroup",
          "ec2:AuthorizeSecurityGroupEgress",
          "ec2:AuthorizeSecurityGroupIngress",
          "ec2:RevokeSecurityGroupEgress",
          "ec2:RevokeSecurityGroupIngress",
          "ec2:CreateTags",
          "ec2:DeleteTags",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSecurityGroupRules",
          "ec2:DescribeVpcs",
          "ec2:DescribeSubnets",
          "ec2:DescribeNetworkInterfaces",
        ]
        Resource = "*"
      },
    ]
  })
}

module "cicd_identity" {
  source = "../../modules/cicd-identity"

  name_prefix     = local.name_prefix
  github_org      = var.github_org
  github_repo     = var.github_repo
  github_owner_id = var.github_owner_id
  github_repo_id  = var.github_repo_id

  allowed_refs         = var.allowed_refs
  create_oidc_provider = var.create_oidc_provider

  # Only used when create_oidc_provider = false.
  existing_oidc_provider_arn = var.existing_oidc_provider_arn

  deploy_policy_json = local.deploy_policy


}
