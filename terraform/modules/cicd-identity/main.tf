# CI/CD identity module: a GitHub Actions OIDC provider + a narrowly-scoped
# deploy role. This lets CI assume a role via short-lived OIDC tokens instead of
# storing long-lived AWS access keys in GitHub secrets.
#
# The trust policy restricts assumption to a specific repository and (optionally)
# ref/branch, so only your pipeline can assume the role. The attached
# permissions should be scoped to exactly what deployment needs; this module
# attaches a caller-supplied policy document rather than a broad managed policy.

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

# Reuse an existing GitHub OIDC provider if one already exists in the account.
resource "aws_iam_openid_connect_provider" "github" {
  count           = var.create_oidc_provider ? 1 : 0
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = var.oidc_thumbprints
  tags            = var.tags
}


locals {
  provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : var.existing_oidc_provider_arn

  # This repo has GitHub's "immutable unique IDs" enabled, so the OIDC token's
  # `sub` claim embeds permanent numeric IDs in a `name@id` form, e.g.
  #   repo:aatikah@14223459/secret-rotation-aws-eks@1430812445:environment:dev
  # The subject prefix below reproduces that exact shape. The repository_id /
  # repository_owner_id conditions further anchor trust to THIS repo even if it
  # (or the org) is ever renamed — names can be reused, IDs cannot.
  repo_subject_prefix = "repo:${var.github_org}@${var.github_owner_id}/${var.github_repo}@${var.github_repo_id}"

  # Allow configured branch refs and the protected dev environment.
  sub_conditions = concat(
    [
      for r in var.allowed_refs :
      "${local.repo_subject_prefix}:ref:${r}"
    ],
    [
      "${local.repo_subject_prefix}:environment:dev"
    ]
  )
}


data "aws_iam_policy_document" "assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = local.sub_conditions
    }
    # Immutable, rename-proof anchor: trust only THIS owner and THIS repo by
    # their permanent numeric IDs. Both must match in addition to the sub above.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:repository_owner_id"
      values   = [var.github_owner_id]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:repository_id"
      values   = [var.github_repo_id]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name                 = "${var.name_prefix}-cicd-deploy"
  assume_role_policy   = data.aws_iam_policy_document.assume.json
  max_session_duration = 3600
  tags                 = var.tags
}

resource "aws_iam_role_policy" "deploy" {
  name   = "${var.name_prefix}-cicd-deploy-policy"
  role   = aws_iam_role.deploy.id
  policy = var.deploy_policy_json
}
