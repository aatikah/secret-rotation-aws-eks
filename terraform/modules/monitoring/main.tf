# Monitoring module: CloudWatch log group, a metric filter that counts rotation
# errors from the structured logs, and alarms for rotation failures and for a
# missing/stale rotation.
#
# The log group is created here (with retention) so the Lambda role can be
# scoped to it. The rotation function emits structured JSON with level=ERROR on
# failure; a metric filter turns those into a CloudWatch metric we can alarm on.

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

resource "aws_cloudwatch_log_group" "rotation" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# Count ERROR-level rotation log lines as a metric.
resource "aws_cloudwatch_log_metric_filter" "rotation_errors" {
  name           = "${var.name_prefix}-rotation-errors"
  log_group_name = aws_cloudwatch_log_group.rotation.name
  # Structured JSON: match records where level == "ERROR".
  pattern = "{ $.level = \"ERROR\" }"

  metric_transformation {
    name          = "RotationErrors"
    namespace     = var.metric_namespace
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "rotation_failure" {
  alarm_name          = "${var.name_prefix}-rotation-failure"
  alarm_description   = "Rotation Lambda emitted one or more ERROR log lines."
  namespace           = var.metric_namespace
  metric_name         = "RotationErrors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_sns_topic_arns
  ok_actions          = var.alarm_sns_topic_arns
  tags                = var.tags
}

# Alarm when the secret has not rotated within its interval + grace period.
# Uses the Secrets Manager-published metric where available; see note in README.
resource "aws_cloudwatch_metric_alarm" "rotation_stale" {
  count               = var.enable_staleness_alarm ? 1 : 0
  alarm_name          = "${var.name_prefix}-rotation-stale"
  alarm_description   = "Secret has not rotated within its configured interval."
  namespace           = "AWS/SecretsManager"
  metric_name         = "DaysSinceLastRotation"
  dimensions          = { SecretName = var.database_secret_name }
  statistic           = "Maximum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = var.rotation_interval_days + var.staleness_grace_days
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = var.alarm_sns_topic_arns
  tags                = var.tags
}
