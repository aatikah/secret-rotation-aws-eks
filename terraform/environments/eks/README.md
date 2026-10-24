# EKS environment (External Secrets Operator)

Fully Terraform-managed EKS cluster plus the External Secrets Operator (ESO) and
every in-cluster object. One `terraform apply` builds the whole Kubernetes
layer; one `terraform destroy` removes it — including the in-cluster objects,
because they are Terraform-managed resources rather than side effects of
`kubectl`. This replaces the old manual `eksctl` / `helm install` /
`kubectl apply` flow.

> **EKS is chargeable** — control plane ~$0.10/hr plus a 2 × t3.medium on-demand
> node group (and a KMS key, EBS volumes, control-plane logs). Review
> `../../../docs/costs.md` before `terraform apply`. Whether and when to deploy
> is your decision.

## What it creates

- `modules/eks`: the EKS cluster, its IAM OIDC provider, a managed node group,
  the cluster/node IAM roles, and a KMS key for **secrets envelope encryption**
  at rest.
- `modules/eks-irsa`: the read-only IRSA role `dev-myapp-eso-reader`, trust
  bound to the cluster OIDC provider and the `myapp:myapp-secrets` service
  account, permission scoped to read `dev/myapp/*` in Secrets Manager.
- The ESO Helm release (chart `external-secrets/external-secrets`, version
  `0.16.2`, `installCRDs=true`), pulling its **default public images** directly
  from `oci.external-secrets.io` over the VPC's NAT gateway — no private ECR
  mirror or image overrides. The release sets `AWS_STS_REGIONAL_ENDPOINTS=regional`
  and `AWS_REGION=us-east-1` on the controller so IRSA uses the in-region STS
  endpoint.
- The in-cluster objects, applied from the canonical YAML in `kubernetes/`:
  namespaces, RBAC, `SecretStore`, `ExternalSecret`, and the sample app. The
  only object reconstructed in HCL is the `myapp-secrets` service account, so
  the real IRSA role ARN is injected in place of the `<ACCOUNT_ID>` placeholder.

The cluster is named `dev-myapp-eks` (from `${environment}-${app_name}` →
`dev-myapp`). The region is **pinned to `us-east-1`** by a variable validation,
because the canonical `20-secretstore.yaml` hardcodes `region: us-east-1` and is
not templated.

## State / backend

This environment holds its **own** S3 state, distinct from dev and network, so a
single `terraform destroy` against this one state removes the whole Kubernetes
layer:

| Setting | Value |
|---|---|
| bucket | `dev-tech-state-bucket` (shared with dev) |
| key | `secrets-rotation/eks/terraform.tfstate` (distinct — never collides with dev or network) |
| region | `us-east-1` |
| encrypt | `true` |
| locking | `use_lockfile = true` (native S3 lock, no DynamoDB table) |

Free validation pass without AWS credentials or the S3 bucket:

```powershell
terraform init -backend=false
terraform validate
```

## Image pulls (NAT, no mirror)

The VPC has a single NAT gateway, so the cluster nodes have normal outbound
internet access. ESO pulls its default public images from
`oci.external-secrets.io` directly, and the sample app pulls `busybox:1.36` from
Docker Hub — both over NAT. There is **no ECR image mirror step** and no
one-time pre-apply sequence: the whole stack comes up in a single
`terraform apply` (see below).

> This replaced an earlier no-NAT design that mirrored the ESO image into a
> private ECR repo because the nodes could not reach public registries. Adding
> the NAT gateway removed that workaround entirely.

### Recovery: a Helm release left created-but-failed by a timed-out apply

If a `terraform apply` times out on the ESO release
(`context deadline exceeded` / "timed out waiting for the condition"), the
release is recorded in state with a `failed` status. Re-run `terraform apply` —
in most cases it reconciles the failed release in place and converges without any
manual helm/terraform surgery. The short-lived EKS auth token (~15 min) is a
common reason a slow first apply just needs a plain, idempotent re-run.

Only if a repeated `terraform apply` keeps failing to progress the release
(e.g. it stays stuck in `pending-install` / `pending-upgrade`) escalate, in this
order:

1. `terraform apply -replace=helm_release.external_secrets` — forces Terraform
   to delete and recreate the release in one step (preferred: keeps state and
   Helm history consistent, no out-of-band kubectl/helm).
2. As a last resort, `helm uninstall external-secrets -n external-secrets`
   out-of-band, then `terraform apply` to recreate. `-replace` is cleaner because
   it avoids the state drift this introduces.

Do **not** `terraform state rm` the release as a recovery step here — that is
only for the half-destroy / cluster-gone scenario in the destroy runbook below.
Removing a live release from state just orphans it.

## Apply (ordering)

Apply the **network** environment first — this env reads its VPC/subnet outputs.
Then, in a single apply (no pre-steps):

```powershell
cd terraform/environments/eks
Copy-Item terraform.tfvars.example terraform.tfvars   # edit as needed
terraform init
terraform plan -out tfplan      # review; nothing is created until apply
terraform apply tfplan
terraform output                # cluster_name, reader_role_arn, oidc_provider_arn, kms_key_arn
aws eks update-kubeconfig --name dev-myapp-eks --region us-east-1   # for kubectl inspection
```

### Single-apply provider model

The `kubernetes`, `helm`, and `kubectl` providers authenticate to the cluster
via the `aws_eks_cluster` / `aws_eks_cluster_auth` data sources. Terraform
creates the cluster first, then configures those providers and applies the Helm
release and manifests — all in one apply. Explicit `depends_on` edges keep ESO's
CRDs installed before the `SecretStore` / `ExternalSecret` custom resources
apply, so there is no "no matches for kind" race. The auth token is short-lived
(~15 min); a very slow apply can be re-run (idempotent) to pick up a fresh token.

## Network-state divergence from dev (read carefully)

The code in `network.tf` mirrors `environments/dev/network.tf`, **but the
variable defaults diverge on purpose**:

| Variable | dev default | this env (eks) default |
|---|---|---|
| `network_state_backend` | `"local"` | `"s3"` |
| `network_state_config` | `{ path = "../network/terraform.tfstate" }` | `{ bucket = "dev-tech-state-bucket-net", key = "secrets-rotation/network/terraform.tfstate", region = "us-east-1" }` |

The eks env defaults to **S3** remote state because it is more likely to run
from CI / a second workstation that does not have the network env's local state
file on disk. **Do not read this as a mirror of dev's defaults.**

If the network environment was actually applied with **local** state, set the
local override, or the remote-state read points at an S3 object that may be
empty or stale and the VPC/subnet lookup fails or returns wrong ids:

```hcl
network_state_backend = "local"
network_state_config  = { path = "../network/terraform.tfstate" }
```

A bring-your-own-VPC path is also available: set `use_network_remote_state =
false` and supply `vpc_id` / `private_subnet_ids`.

## Node sizing

Defaults are 2 × `t3.medium` on-demand (`node_desired_size = 2`,
`node_min_size = 1`, `node_max_size = 3`). For a cheaper disposable demo, a
single `t3.small`:

```hcl
node_instance_type = "t3.small"
node_desired_size  = 1
node_min_size      = 1
node_max_size      = 1
```

## Destroy (and the half-destroy recovery)

Teardown order is **eks → dev → network** (destroy this env before the network
env it reads). Run `terraform destroy` **while the cluster still exists** — the
in-cluster providers need a token for the live cluster to delete the Kubernetes
objects, which Terraform tears down first (manifests, then node group, then
cluster, then OIDC/KMS/IAM).

If a destroy is interrupted after the cluster is gone but with in-cluster
resources still in state, the providers can no longer get a token and re-running
destroy fails to plan. Remove **only** the orphaned in-cluster entries from
state (they died with the cluster), then re-run destroy. Preview exactly which
addresses are safe to remove:

```powershell
terraform state list | Select-String '^(helm_release|kubernetes_service_account_v1|kubectl_manifest)\.'
```

**Safe to `terraform state rm`** (in-cluster objects, already gone with the
cluster):

- `helm_release.external_secrets`
- `kubernetes_service_account_v1.myapp_secrets`
- every `kubectl_manifest.*` address (`kubectl_manifest.namespaces[*]`,
  `.rbac[*]`, `.secretstore`, `.externalsecret`, `.sample_app`)

**NEVER `state rm`** these — they are real AWS resources, and removing them from
state orphans them in AWS (the opposite of a clean teardown):

- anything under `module.eks.*` (cluster, node group, OIDC provider, KMS key,
  KMS alias, cluster/node IAM roles + attachments)
- anything under `module.eks_irsa.*` (the reader role + inline policy)

Known residue after destroy: AWS keeps the control-plane log group
`/aws/eks/dev-myapp-eks/cluster`, and the KMS key enters a 7-day deletion window
rather than deleting immediately.

See `../../../docs/deployment.md` sections 6 and 8 for the full runbook.
