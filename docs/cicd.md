# CI/CD with GitHub Actions

Pipeline: `.github/workflows/ci.yml`.

## What runs on every PR / push to main

| Job | Steps |
|---|---|
| `quality` | ruff lint, mypy type check, unit tests + coverage (integration excluded), `pip-audit` dependency scan, gitleaks secret scan |
| `terraform` | `terraform fmt -check`, `init -backend=false`, `validate` (no AWS, no apply) |
| `package` | build the rotation Lambda zip, assert `handler.py` + `secrets_rotation/` + vendored `psycopg` are present, upload artifact |

These three jobs need no cloud credentials and never touch AWS.

## Deployment (manual, gated)

`deploy-dev` runs **only** via `workflow_dispatch` with `deploy_dev = true`, and
only after `quality`, `terraform`, and `package` pass. It:

1. Assumes an AWS role via **GitHub OIDC** (`id-token: write`) — no long-lived
   keys in repo secrets.
2. Builds the Lambda package.
3. Runs `terraform plan` then `apply` for the dev environment.

### Required repo configuration

- A GitHub **environment** named `dev` with required reviewers (approval gate).
  Production would be a separate, more restricted environment.
- Repo **secret** `AWS_DEPLOY_ROLE_ARN` = the `deploy_role_arn` output of the
  `cicd` bootstrap environment (below).
- Repo **variable** `AWS_REGION`.

### OIDC setup (one time)

Apply the dedicated bootstrap environment `terraform/environments/cicd`, which
instantiates the `cicd-identity` module. It is a **separate environment** (not
part of `dev`) on purpose: the deploy role cannot be managed by the very apply
it authorizes. The environment:

- creates the GitHub Actions OIDC provider (or reuses an existing one via
  `create_oidc_provider = false` + `existing_oidc_provider_arn`);
- creates the deploy role with a trust policy locked to your repo and
  `allowed_refs` (default `refs/heads/main`);
- attaches a **least-privilege** inline policy scoped to exactly what a `dev`
  apply needs — Secrets Manager (`dev/myapp/*`), the rotation Lambda + its IAM
  role, CloudWatch Logs/alarms, RDS, the Lambda security group, and read/write
  of the dev Terraform state in S3 (plus read of the network state) — not
  account-wide admin.

```powershell
cd terraform\environments\cicd
Copy-Item terraform.tfvars.example terraform.tfvars   # set github_org + github_repo
terraform init
terraform apply
terraform output github_setup_hint    # the exact GitHub secret/variable/env values
```

See `terraform/environments/cicd/README.md` for the full runbook and the
OIDC-provider-uniqueness caveat (an account allows only one GitHub OIDC
provider).

## Safety choices

- **No real rotation in CI's quality gate.** The `quality` job runs pure-logic
  unit tests (no AWS); it never calls `rotate-secret`. The AWS integration tests
  (`RUN_AWS_INTEGRATION=1`) run only in the gated deploy path against a
  disposable environment.
- **Least-privilege deploy.** Short-lived OIDC credentials, scoped role,
  protected environment with reviewers.
- **Secret scanning + dependency audit** fail the build on findings, so a
  committed credential or a vulnerable dependency blocks merge.

## Verified locally

The `quality` job's static and unit checks pass on the workstation: `ruff check`
(clean), `mypy` (clean), `pytest tests\unit` (pure-logic suite). The workflow
YAML parses correctly. The GitHub-hosted run executes on push to the repo; the
AWS integration tests and deploy run against your AWS account.
