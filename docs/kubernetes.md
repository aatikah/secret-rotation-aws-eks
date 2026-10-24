# Kubernetes secrets integration

Delivers AWS Secrets Manager values into Kubernetes via the External Secrets
Operator (ESO). Manifests live in `kubernetes/`.

## The flow

```
AWS Secrets Manager  --(ESO reads via IRSA)-->  Kubernetes Secret  --(env/volume)-->  Pod
```

1. `SecretStore` tells ESO how to reach Secrets Manager (region + workload
   identity).
2. `ExternalSecret` declares which AWS secret maps to which Kubernetes Secret
   and the `refreshInterval`.
3. ESO creates and owns the Kubernetes `Secret`; the app consumes it.

## The refresh caveat (important)

Refreshing a Kubernetes `Secret` does **not** reload an already-running process.
Two consumption patterns behave differently:

- **Env vars (`envFrom`)**: captured once at container start. A rotated value is
  NOT seen until the pod restarts.
- **Mounted volume**: the kubelet updates the files when the Secret changes, so
  an app that re-reads the file sees the new value without a restart.

The sample app (`kubernetes/sample-app/deployment.yaml`) uses both so you can
observe the difference. For a guaranteed refresh, use a reloader
(stakater/reloader auto annotation is included) or `kubectl rollout restart`.

## Least privilege

- The app service account's IAM role is scoped to **read** `dev/myapp/*` only —
  not write, not other namespaces' secrets. It is provisioned by the
  `terraform/modules/eks-irsa` module (role `dev-myapp-eso-reader`), whose inline
  policy grants exactly `secretsmanager:GetSecretValue`, `DescribeSecret`, and
  `ListSecretVersionIds` on `dev/myapp/*` — never broad `secretsmanager:*`.
- RBAC (`kubernetes/policies/rbac.yaml`) lets the app read only its own Secret.
- Namespaces isolate operator / store / app.

## Authentication on EKS

Use IRSA (IAM Roles for Service Accounts) or EKS Pod Identity. The `SecretStore`
authenticates with `auth.jwt.serviceAccountRef`, so the pod assumes the IAM role
annotated on its service account — no static AWS keys live in the cluster. The
role is scoped to **read** `dev/myapp/*` only. It is created by the
`terraform/modules/eks-irsa` module and bound to the cluster's OIDC provider and
the `myapp:myapp-secrets` service account; the `terraform/environments/eks`
environment annotates the service account with the role ARN automatically. See
`deployment.md` section 6.

Protect the synced Secret with encryption at rest — the `terraform/modules/eks`
cluster enables **EKS KMS envelope encryption** (`encryption_config` with a
customer-managed KMS key) for Kubernetes Secrets — plus RBAC
(`kubernetes/policies/rbac.yaml`) and namespace isolation.

## What was verified

All manifests parse as valid YAML (checked with a YAML loader). Apply and
verification steps are in `kubernetes/external-secrets/README.md` and
`deployment.md` section 6.
