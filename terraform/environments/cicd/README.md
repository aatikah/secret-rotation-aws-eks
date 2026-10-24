# CI/CD identity bootstrap environment

Creates the **GitHub Actions OIDC provider** and a **least-privilege deploy
role** that the `deploy-dev` job in `.github/workflows/ci.yml` assumes via
short-lived OIDC tokens — so no long-lived AWS keys are stored in GitHub.

Apply this **once, locally**, with elevated (bootstrap) credentials. CI never
applies this environment; it only consumes the `deploy_role_arn` output.

## Why a separate environment

The deploy role cannot live in the `dev` env, because `dev` is the very thing CI
deploys *using* this role — that would be circular. Giving the CI identity its
own state (matching the `network` / `dev` / `eks` split) breaks the bootstrap
paradox and keeps IAM identity resources isolated from app teardown.

## What it creates

- `aws_iam_openid_connect_provider.github` — the account-wide GitHub Actions
  OIDC provider (`token.actions.githubusercontent.com`). An account can have
  only **one**; if yours already exists, set `create_oidc_provider = false` and
  pass `existing_oidc_provider_arn`.
- `aws_iam_role` `${env}-${app}-cicd-deploy` — trust policy locked to
  `repo:<org>/<repo>:ref:<allowed_refs>` and `aud = sts.amazonaws.com`.
- An inline **least-privilege** policy scoping exactly what a `dev` apply needs:
  Secrets Manager (`dev/myapp/*`), the rotation Lambda + its IAM role,
  CloudWatch Logs + alarms, RDS, a Lambda security group, and read/write to the
  dev Terraform state in S3 (plus read of the network remote state).

## Apply (one time)

```powershell
cd terraform\environments\cicd
Copy-Item terraform.tfvars.example terraform.tfvars
# Edit: github_org, github_repo (required). Adjust allowed_refs / region if needed.

terraform init
terraform plan -out tfplan     # review
terraform apply tfplan
terraform output               # deploy_role_arn, github_setup_hint
```

### Free validation (no AWS, no credentials)

```powershell
terraform init -backend=false
terraform validate
```

## Then wire GitHub (see `terraform output github_setup_hint`)

1. Repo **secret** `AWS_DEPLOY_ROLE_ARN` = the `deploy_role_arn` output.
2. Repo **variable** `AWS_REGION` (e.g. `us-east-1`) — a *variable*, not a secret.
3. A `dev` **environment** with required reviewers (the approval gate).

Then run the workflow manually (`workflow_dispatch`) with `deploy_dev = true`
from a branch listed in `allowed_refs`.

## Prerequisites

- The S3 state bucket(s) exist and the `network` env is applied (the `dev` apply
  that CI runs reads the network remote state).
- Your local identity can create IAM/OIDC resources and read/write this env's
  state object (`secrets-rotation/cicd/*`).

## Destroy

```powershell
terraform destroy
```

> If you reused an existing OIDC provider (`create_oidc_provider = false`),
> destroy removes only the role — it will not delete the shared provider.
> Destroying this env revokes CI's ability to deploy; do it after you no longer
> need the pipeline.

## Note on the OIDC thumbprint

The module defaults `oidc_thumbprints` to GitHub's published root CA thumbprint.
Modern AWS OIDC validation for GitHub no longer strictly depends on it, but
verify against GitHub's current docs if an assume-role call ever fails on trust.
