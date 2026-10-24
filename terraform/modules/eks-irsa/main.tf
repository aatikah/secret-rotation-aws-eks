# IRSA reader role for External Secrets Operator (ESO).
#
# This module owns ONLY the IAM role ESO's service account assumes via IRSA and
# its inline read-only policy. It receives the cluster OIDC provider ARN/URL
# (from modules/eks) and emits the role ARN so the environment can annotate the
# myapp:myapp-secrets service account with it.
#
# Trust: federated to the cluster OIDC provider, locked with StringEquals on
# BOTH the sub (exact namespace/service account) and aud (sts.amazonaws.com) —
# no wildcard, so only myapp:myapp-secrets can assume the role.
#
# Permission: read-only on dev/myapp/* in Secrets Manager (GetSecretValue,
# DescribeSecret, ListSecretVersionIds). No write, no "*". The region is
# single-sourced from var.aws_region; the account id comes from the caller
# identity, so neither is hardcoded.

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

data "aws_caller_identity" "current" {}

# Trust policy: who may assume this role, and under what OIDC claims.
data "aws_iam_policy_document" "assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    # Exact service account — no wildcard. Least privilege.
    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider_url}:sub"
      values   = ["system:serviceaccount:${var.namespace}:${var.service_account}"]
    }

    # Audience must be the STS audience the EKS OIDC provider is registered for.
    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "reader" {
  name               = var.role_name
  assume_role_policy = data.aws_iam_policy_document.assume.json

  # Tags come from the caller. Keep this {} at the environment level so the
  # provider default_tags (capitalized Project/Environment/ManagedBy/Owner)
  # supply the standard set — a lowercase duplicate here would make CreateRole
  # fail with "Duplicate tag keys" (IAM compares tag keys case-insensitively).
  tags = var.tags
}

# Inline read-only policy, scoped to the dev/myapp/* secret ARN. The trailing
# "*" in secret_prefix covers both the name hierarchy and the random 6-char
# suffix Secrets Manager appends to every secret ARN.
resource "aws_iam_role_policy" "read" {
  name = "${var.role_name}-read"
  role = aws_iam_role.reader.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
          "secretsmanager:ListSecretVersionIds",
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.secret_prefix}"
      },
    ]
  })
}
