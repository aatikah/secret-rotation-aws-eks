# Testing and failure simulation guide (AWS)

How to test every layer and deliberately simulate failures to prove recovery.
Testing and simulation run **on AWS** against a deployed environment; the only
workstation-local checks are static analysis and pure-logic unit tests that gate
a deploy.

All commands use Windows PowerShell from the repo root unless noted. Git Bash:
replace `.\.venv\Scripts\python.exe` with `python` after activating the venv.

---

## 1. Test levels

| Level | What it covers | Needs | Command |
|---|---|---|---|
| Static | Lint, types | dev extras | `ruff check src tests lambda scripts`, `mypy` |
| Unit (pure logic) | Password gen, alternating-users mapping, cert expiry, policy, audit parsing, redaction | nothing (no AWS) | `pytest tests\unit` |
| AWS integration | Real rotation via Secrets Manager + RDS; API rotation staging | deployed env + `RUN_AWS_INTEGRATION=1` | `pytest -m integration` |
| IaC | Terraform correctness | Terraform | `terraform validate` (in `environments/dev`) |
| CI | All of the above, gated | GitHub | `.github/workflows/ci.yml` |

### Pre-deploy checks (workstation, no AWS)

```powershell
.\.venv\Scripts\ruff.exe check src tests lambda scripts
.\.venv\Scripts\mypy.exe
.\.venv\Scripts\python.exe -m pytest tests\unit
```

---

## 2. AWS integration tests

Requires a deployed `dev` environment with RDS (see `deployment.md`), AWS
credentials, and the enable flag:

```powershell
$env:RUN_AWS_INTEGRATION = "1"
$env:AWS_REGION          = "us-east-1"
$env:SECRET_ID           = "dev/myapp/database"
$env:API_SECRET_ID       = "dev/myapp/external-api"
.\.venv\Scripts\python.exe -m pytest -m integration -rs
```

What they assert against the real services:

- `test_database_rotation_aws.py`: triggers a managed rotation, waits for it to
  settle, confirms `AWSCURRENT` advanced, `AWSPREVIOUS` is retained, and the
  rotated credential authenticates against RDS; a concurrent rotation is
  rejected.
- `test_api_rotation_aws.py`: stages a pending API key in real Secrets Manager,
  validates it via the mock provider, promotes it, and confirms the old key is
  retired only after a successful transition.

Without `RUN_AWS_INTEGRATION=1` or credentials, these tests skip cleanly (they
never fail for lack of an environment).

---

## 3. Failure simulation on AWS (`scripts/simulate_failures.py`)

Drives failure modes against the deployed secret, rotation Lambda, and RDS:

```powershell
.\.venv\Scripts\python.exe scripts\simulate_failures.py --secret-id dev/myapp/database
.\.venv\Scripts\python.exe scripts\simulate_failures.py --secret-id dev/myapp/database --only 1
```

| Drill | Failure | Expected recovery |
|---|---|---|
| 1 | Rotation that fails validation (unreachable DB / missing grant) | `AWSCURRENT` unchanged; `dev-myapp-rotation-failure` alarm fires |
| 2 | Concurrent / duplicate rotation | second request rejected; no state corruption |
| 3 | Overdue / stale rotation | surfaced by the `DaysSinceLastRotation` alarm and the policy checker |

### Inducing drill 1's failure condition

Make the database unreachable to the Lambda, then run drill 1:

```powershell
# Example: temporarily remove the SG ingress rule the Lambda uses to reach 5432,
# or point the secret host at an unreachable value. Then:
.\.venv\Scripts\python.exe scripts\simulate_failures.py --secret-id dev/myapp/database --only 1
aws logs tail /aws/lambda/dev-myapp-db-rotation --since 10m --follow
```

The rotation fails at `testSecret`, `AWSCURRENT` does not move, and the failure
alarm enters ALARM. Restore the rule and re-run to confirm recovery (rotation
completes, `AWSCURRENT` advances).

### Transient error + retry

Secrets Manager retries a failed rotation step automatically. Induce a brief
network blip during rotation (detach/re-attach the SG rule) and confirm the next
attempt completes. Rotation is idempotent, so no duplicate credential is created.

---

## 4. Policy and audit checks on AWS

```powershell
# Export live secret metadata to the descriptor shape, then evaluate it:
.\.venv\Scripts\secrets-rotation policy-check --input <your-descriptors.json>

# Summarise real CloudTrail events (export them to JSON first):
aws cloudtrail lookup-events --lookup-attributes `
  AttributeKey=EventSource,AttributeValue=secretsmanager.amazonaws.com `
  --max-results 50 > events.json
.\.venv\Scripts\secrets-rotation audit-report --input events.json

# Print ready-to-paste investigation queries for CloudWatch Logs Insights /
# CloudTrail Lake:
.\.venv\Scripts\secrets-rotation cw-queries
```

The policy checker distinguishes a confirmed violation (`FAIL`) from
missing-data (`UNKNOWN`), and exits non-zero on a confirmed violation so CI can
gate on it.

---

## 5. Kubernetes refresh simulation (EKS)

```bash
kubectl logs -n myapp deploy/myapp -f           # shows the configured DB user
aws secretsmanager rotate-secret --secret-id dev/myapp/database
# Mounted-file value updates within refreshInterval (1m) WITHOUT a restart;
# the env-var copy only changes after a pod restart:
kubectl rollout restart deploy/myapp -n myapp
```

This demonstrates the application-refresh caveat: syncing the Kubernetes Secret
does not reload an already-running process unless it re-reads the file or is
restarted.

---

## 6. Acceptance criteria coverage

| Criterion | Where proven |
|---|---|
| Successful DB rotation | `test_database_rotation_aws.py`, section 5 of `deployment.md` |
| Failed DB rotation doesn't promote | simulate drill 1 (AWS) |
| Retry after transient error | §3 transient-error procedure (AWS) |
| Invalid DB credentials rejected | integration test authenticates rotated creds against RDS |
| Idempotent invocation | rotation design + `test_rotation_logic.py` (step dispatch) |
| Concurrent-attempt safety | `test_concurrent_rotation_is_rejected`, simulate drill 2 |
| Validation before promotion | state-machine design, simulate drill 1 |
| Failed API replacement | `test_api_rotation_aws.py` (rollback path on validation failure) |
| Expired certificate detection | `test_certificates.py` |
| K8s secret synchronization | ESO `ExternalSecret` + §5 |
| Application credential refresh | sample app + §5 |
| Policy violation detection | `test_policy.py`, CLI `policy-check` |
| Access-denied behaviour | IAM least privilege + audit report (AccessDenied events) |
| Redaction of secrets from logs | `test_logging_redaction.py` |
| CI/CD validation | `.github/workflows/ci.yml` |
| Reproducible + destroyable infra | Terraform `apply`/`destroy`, `cleanup.py` |
