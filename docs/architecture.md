# Architecture decisions

This document explains the choices behind the platform before the AWS stages
provision anything. The goal is a modular design that works locally and scales
to AWS without forcing a production Kubernetes cluster on day one.

## Logical components

| Component | Role | Stage |
|---|---|---|
| AWS Secrets Manager | Secret storage + version staging (`AWSCURRENT`/`AWSPENDING`/`AWSPREVIOUS`) | 2 |
| AWS Lambda (Python) | Custom rotation logic invoked per step | 2–3 |
| EventBridge / native schedule | Triggers scheduled rotation | 2 |
| CloudTrail | Audit of Secrets Manager API activity | 2 |
| CloudWatch | Rotation logs, metrics, alarms | 2 |
| RDS / disposable PostgreSQL | Database-password rotation target | 3 |
| IAM | Least-privilege roles/policies | 2 |
| External Secrets Operator | Sync Secrets Manager → Kubernetes Secret | 4 |
| GitHub Actions | CI/CD with OIDC federation | 5 |
| Terraform | Infrastructure as code | 2 |

## Staging labels: the mechanism that makes rotation safe

Secrets Manager attaches moving labels to secret versions:

- **`AWSCURRENT`** — what applications read now.
- **`AWSPENDING`** — the candidate created and tested during rotation.
- **`AWSPREVIOUS`** — the version just demoted from current, kept for recovery.

Rotation never edits a version in place. It creates a new version
(`AWSPENDING`), validates it, then *moves* the `AWSCURRENT` label to it. Moving
`AWSCURRENT` automatically demotes the old version to `AWSPREVIOUS`. If anything
fails before the label moves, applications keep reading the unchanged
`AWSCURRENT` — rotation is safe by construction.

## External Secrets Operator vs Secrets Store CSI Driver

Both bring AWS Secrets Manager values into Kubernetes, but differently:

**External Secrets Operator (ESO) — chosen as primary**
- Reads from Secrets Manager and *writes a native Kubernetes `Secret`*.
- Any workload that already consumes a `Secret` (env var or volume) works
  unchanged — no app or pod-spec coupling to a CSI driver.
- Refreshes on a configurable `refreshInterval`; good for incremental adoption.
- Trade-off: the secret value lands in etcd as a Kubernetes `Secret` (mitigated
  by encryption at rest + RBAC + namespace isolation).

**Secrets Store CSI Driver**
- *Mounts* secret material as files into a pod volume at runtime; nothing is
  written to a Kubernetes `Secret` unless you enable sync.
- Keeps material out of etcd by default (a security plus for some threat
  models), but couples the pod spec to a CSI volume and a `SecretProviderClass`.

**Synchronizing vs mounting — the core difference.** Synchronizing (ESO)
produces a Kubernetes `Secret` object other resources reference by name.
Mounting (CSI) projects files into one pod's filesystem; there is no shared
`Secret` object unless sync is turned on. For a first project that must work
with ordinary Deployments, ESO is the lower-friction, more portable choice.

## Two CloudTrail event categories (not interchangeable)

- **Management events** (on by default): control-plane calls such as
  `RotateSecret`, `UpdateSecretVersionStage`, `PutSecretValue`,
  `DescribeSecret`. They tell you rotation happened and who changed config.
- **Secret-value retrieval** (`GetSecretValue`): the read of actual material.
  To reliably capture high-volume read patterns you must ensure the trail/event
  selectors cover it — do not assume the default management trail captures every
  sensitive access.

The audit module (`src/secrets_rotation/audit/reporting.py`) classifies both and
the CLI emits example Logs Insights / CloudTrail Lake queries to investigate
failures and unusual access.

## Why a disposable, non-public database

Database-rotation testing (Stage 3) uses a disposable PostgreSQL with no public
ingress (private subnet / security group, or a local container). A publicly
reachable database is never created. Costs are called out before any `apply`.
