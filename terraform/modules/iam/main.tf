# IAM module: least-privilege execution role for the rotation Lambda.
#
# The role grants ONLY:
#   - the Secrets Manager actions rotation needs, scoped to the specific
#     secret ARNs (not secretsmanager:* on all secrets);
#   - permission to read the master secret;
#   - GetRandomPassword (used when generating passwords server-side);
#   - CloudWatch Logs write for its own log group;
#   - VPC ENI management ONLY when the Lambda runs in a VPC (to reach a private
#     database). Controlled by var.vpc_access.

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

data "aws_iam_policy_document" "assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "rotation" {
  name               = "${var.name_prefix}-rotation-lambda"
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "rotation" {
  # Secrets Manager rotation on the specific secrets only.
  statement {
    sid    = "SecretsManagerRotation"
    effect = "Allow"
    actions = [
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetSecretValue",
      "secretsmanager:PutSecretValue",
      "secretsmanager:UpdateSecretVersionStage",
    ]
    resources = var.rotatable_secret_arns
  }

  # The master secret is read-only to the rotation function.
  statement {
    sid       = "ReadMasterSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [var.master_secret_arn]
  }

  # Server-side password generation.
  statement {
    sid       = "GetRandomPassword"
    effect    = "Allow"
    actions   = ["secretsmanager:GetRandomPassword"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "rotation" {
  name   = "${var.name_prefix}-rotation-policy"
  role   = aws_iam_role.rotation.id
  policy = data.aws_iam_policy_document.rotation.json
}

# Basic Lambda logging (scoped to this function's log group ARN).
data "aws_iam_policy_document" "logs" {
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${var.log_group_arn}:*"]
  }
  statement {
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup"]
    resources = ["arn:aws:logs:${var.aws_region}:${var.account_id}:*"]
  }
}

resource "aws_iam_role_policy" "logs" {
  name   = "${var.name_prefix}-rotation-logs"
  role   = aws_iam_role.rotation.id
  policy = data.aws_iam_policy_document.logs.json
}

# Attach the AWS-managed VPC access policy only when the Lambda needs to reach
# a database inside a VPC. ENI create/delete is required for VPC Lambdas.
resource "aws_iam_role_policy_attachment" "vpc" {
  count      = var.vpc_access ? 1 : 0
  role       = aws_iam_role.rotation.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}
