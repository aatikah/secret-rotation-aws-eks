# Status and component map

This project deploys, tests, and simulates on AWS. The only workstation-local
work is the developer toolchain (install, lint, type check, pure-logic unit
tests, Lambda packaging). Nothing is deployed and no real rotation runs without
an explicit `terraform apply` / `rotate-secret` against your AWS account.

## Components

### Application / rotation logic (Python)

- Installable library: config + naming convention, structured logging with
  secret redaction, database rotation state machine (four steps, alternating
  users), API credential rotation, certificate lifecycle, policy compliance
  checker, audit reporting.
- Thin Lambda handler (`lambda/database_rotation/handler.py`) wiring the DB
  rotation to the Secrets Manager event contract.
- CLI (`secrets-rotation`) with `policy-check`, `audit-report`, `cw-queries`.
- Operator scripts (AWS-targeted): `create_dummy_secret.py`, `verify_rotation.py`,
  `simulate_failures.py`, `cleanup.py`, `build_lambda.py`.

Verification (workstation): `ruff` clean, `mypy` clean, pure-logic unit suite
passing (`pytest tests\unit`).

### Infrastructure (Terraform)

- Modules: `secrets-manager`, `rotation-lambda`, `iam`, `monitoring`,
  `database` (private RDS PostgreSQL), `cicd-identity` (GitHub OIDC).
- `environments/dev` composes them; the secret's `db_host` is wired from the RDS
  endpoint automatically. Provider pins (AWS 6.x), optional encrypted S3 backend
  with locking.

Verification: `terraform fmt -check` passes. (The heavier `validate` runs in CI
and on your workstation when the provider plugins load.) `terraform apply`
requires AWS credentials and creates chargeable resources — see `costs.md`.

### Kubernetes (EKS + External Secrets Operator)

- ESO manifests under `kubernetes/external-secrets/`: namespaces, IRSA service
  account, `SecretStore` (workload-identity auth, no static keys), and an
  `ExternalSecret` syncing `dev/myapp/database`.
- `kubernetes/sample-app/`: a Deployment consuming the Secret via BOTH env vars
  (restart-to-refresh) and a mounted volume (refresh-without-restart), to
  demonstrate the application-refresh caveat.
- `kubernetes/policies/rbac.yaml`: least-privilege Role scoped to the one Secret.

Verification: manifests parse as valid YAML. Apply/verify on EKS per
`deployment.md` section 6.

### CI/CD (GitHub Actions)

- `.github/workflows/ci.yml`: `quality` (ruff, mypy, unit tests + coverage,
  pip-audit, gitleaks), `terraform` (fmt/validate), `package` (build +
  sanity-check the Lambda zip), and a manual, OIDC-gated `deploy-dev` behind a
  protected environment.
- `environments/cicd`: a one-time bootstrap env that instantiates the
  `cicd-identity` module — the GitHub OIDC provider + the scoped deploy role the
  `deploy-dev` job assumes. Applied locally; CI only consumes its output.
- `Dockerfile`: non-root image for the operator CLI/library.
- No long-lived AWS keys (OIDC); no real rotation in the quality gate.

### Testing & simulation (on AWS)

- AWS integration tests (`tests/integration`, `RUN_AWS_INTEGRATION=1`): managed
  rotation advances `AWSCURRENT`, retains `AWSPREVIOUS`, and the rotated
  credential authenticates against RDS; concurrent rotation is rejected; API
  rotation promotes and retires the old key.
- Failure drills (`scripts/simulate_failures.py`): failed-validation (no
  promotion + alarm), concurrent rotation rejected, overdue detection.

See `testing-and-simulation.md` for exact commands and `deployment.md` for the
full runbook.

## Acceptance criteria

Pure-logic criteria are covered by the unit suite (password generation,
alternating-users mapping, cert expiry, policy violations incl. missing-data
UNKNOWN, audit parsing, secret redaction). The AWS-dependent criteria
(successful/failed rotation, retry, validate-before-promote, concurrent safety,
API retire-after-transition, K8s sync, app refresh, audit on real CloudTrail,
reproducible teardown) are exercised by the AWS integration tests, the failure
drills, and the deployment runbook against your AWS account.
