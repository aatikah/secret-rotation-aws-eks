# Troubleshooting

Common errors and fixes, grouped by stage.

## Toolchain / Python (workstation)

**`pip install -e ".[dev]"` fails building a wheel**
Ensure Python 3.11+ (`python --version`). On Windows, `psycopg[binary]` ships a
wheel so no compiler is needed; if it still fails, upgrade pip
(`python -m pip install --upgrade pip`).

**`secrets-rotation` command not found**
Use the venv entry point: `.\.venv\Scripts\secrets-rotation` (Windows) or
activate the venv first.

## AWS integration tests

**All integration tests skip**
Expected unless you opt in. Set `RUN_AWS_INTEGRATION=1`, provide AWS
credentials, and ensure the `dev` environment is deployed. Without those, the
tests skip cleanly rather than fail.

**Integration test skips: "rotation not enabled" / "secret not found"**
The environment is not fully deployed. Apply Terraform with `create_database =
true` (so rotation is wired to a reachable RDS), and seed the API secret with
`scripts/create_dummy_secret.py` before the API test.

## Terraform

**`terraform validate` succeeds but `plan` asks for credentials**
`validate` needs no AWS; `plan`/`apply` do. Run `aws sts get-caller-identity`
and set your region/profile.

**`archive_file` error: source directory not found**
Build the Lambda package first: `python scripts/build_lambda.py`. The
`build/package/` dir must exist (its `.gitkeep` is tracked so a fresh clone
validates, but a real plan/apply needs the built contents).

**Cycle error between the secret and the Lambda**
Already resolved: the `aws_secretsmanager_secret_rotation` resource lives at the
environment level (`environments/dev/main.tf`), not inside the secrets module.
Don't move it back into the module.

**State contains a password**
Expected for the bootstrap `random_password`. Use the encrypted S3 backend and
restrict access (see `terraform-state.md`). The first rotation replaces the live
value and `ignore_changes` hands ownership to Secrets Manager.

## Rotation (AWS)

**Rotation stuck / `testSecret` always fails**
Check the Lambda can reach the database: if the DB is in a VPC, the Lambda must
be in the same VPC with a security group allowed to reach port 5432. Set
`create_database = true` (which enables VPC access) or supply `subnet_ids` /
`security_group_ids`. Inspect logs:
`aws logs tail /aws/lambda/dev-myapp-db-rotation --since 15m`.

**`AWSPENDING` left dangling after a failure**
Safe: the next successful rotation overwrites it, and `AWSCURRENT` never moved,
so the app is unaffected. To cancel a stuck rotation:
`aws secretsmanager cancel-rotate-secret --secret-id dev/myapp/database`.

**Alarm `*-rotation-failure` firing**
The Lambda emitted an ERROR log line. Open the log group, find the structured
record (it is redacted — no secret values), fix the cause (DB reachability,
master grant), and re-run `rotate-secret`.

## Kubernetes / ESO

**`ExternalSecret` shows `SecretSyncedError`**
Usually auth. Confirm the service-account IAM role ARN annotation on
`myapp-secrets` and that the role's trust policy binds the EKS OIDC provider to
this namespace + service account. Confirm the role has read access to
`dev/myapp/*`.

**App doesn't see the rotated value**
Expected for env-var consumption until a restart. The mounted-file value updates
within `refreshInterval`. Install stakater/reloader or
`kubectl rollout restart deploy/myapp -n myapp`.

**`kubectl get secret` shows the value base64-encoded**
That is normal Kubernetes encoding, not encryption. Enable encryption at rest
(EKS: KMS envelope encryption). Never print or commit the decoded value.

## CI/CD

**OIDC `AssumeRoleWithWebIdentity` denied**
The deploy role trust policy must allow this repo and ref. Check the `sub`
condition matches `repo:<org>/<repo>:ref:refs/heads/main` and the audience is
`sts.amazonaws.com`.

**gitleaks fails the build**
A secret-looking string was committed. Remove it, rotate it if it was real, and
rely on Secrets Manager for actual values. Test fixtures use fake values only.
