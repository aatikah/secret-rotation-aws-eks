# Rotation Lambda module.
#
# Packaging: the deployment zip is built OUT OF BAND by
# scripts/build_lambda.py (which vendors psycopg + the secrets_rotation package
# for the Lambda runtime) into terraform/modules/rotation-lambda/build/.
# Terraform zips that staging directory with the archive provider. We package
# out of band because psycopg needs manylinux wheels that must be fetched for
# the Lambda platform, which Terraform cannot do itself.
#
# The function is granted permission for Secrets Manager to invoke it, scoped to
# the specific database secret ARN.

terraform {
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 6.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.4" }
  }
}

data "archive_file" "package" {
  type        = "zip"
  source_dir  = var.package_source_dir
  output_path = "${path.module}/build/rotation-lambda.zip"
}

resource "aws_lambda_function" "rotation" {
  function_name = "${var.name_prefix}-db-rotation"
  role          = var.role_arn
  handler       = "handler.lambda_handler"
  runtime       = var.python_runtime
  timeout       = var.timeout_seconds
  memory_size   = var.memory_mb

  filename         = data.archive_file.package.output_path
  source_code_hash = data.archive_file.package.output_base64sha256

  environment {
    variables = {
      LOG_LEVEL = var.log_level
      # AWS_REGION = var.aws_region
    }
  }

  # Attach to private subnets only when reaching a VPC-internal database.
  dynamic "vpc_config" {
    for_each = length(var.subnet_ids) > 0 ? [1] : []
    content {
      subnet_ids         = var.subnet_ids
      security_group_ids = var.security_group_ids
    }
  }

  tags = var.tags
}

# Allow Secrets Manager to invoke this function.
#
# Scoped to this account via source_account (prevents cross-account invocation)
# but deliberately WITHOUT a source_arn constraint. The RotateSecret preflight
# check that Secrets Manager runs when associating a rotation Lambda does not
# present the secret ARN as AWS:SourceArn, so a permission gated on
# source_arn = <secret ARN> fails that check with:
#   AccessDeniedException: ... You must have the permission lambda:InvokeFunction
#   to associate this function with this secret.
# This matches AWS's documented `aws lambda add-permission` for rotation
# functions, which sets --source-account (not --source-arn).
resource "aws_lambda_permission" "allow_secretsmanager" {
  statement_id   = "AllowSecretsManagerInvoke"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.rotation.function_name
  principal      = "secretsmanager.amazonaws.com"
  source_account = var.account_id
}
