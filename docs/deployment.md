# Deployment runbook (AWS)

End-to-end instructions to deploy, test, and simulate the platform **on AWS**.
This project is designed to run on AWS: Secrets Manager, a rotation Lambda, RDS
PostgreSQL, CloudWatch, IAM, and (optionally) EKS with External Secrets
Operator. There is no local deployment path — the only thing that runs on your
workstation is the developer toolchain (install, lint, type check, pure-logic
unit tests) used before you deploy.

> **Golden rule:** read `costs.md` before any `terraform apply`. The database
> (RDS) and EKS are the main cost drivers. Destroy disposable resources when
> done (section 8).

Working directories are stated for every step. Commands are Windows PowerShell;
Git Bash equivalents are noted where they differ.

---

## 0. Prerequisites

See `prerequisites.md`: Python 3.11+, Git, AWS CLI v2 (+ credentials),
Terraform, and — for inspecting the Terraform-provisioned Kubernetes stage —
kubectl. (Helm and the ESO install are handled by Terraform; `eksctl` is no
longer needed.)

Confirm your AWS identity and region before any step:

```powershell
aws sts get-caller-identity
$env:AWS_REGION = "us-east-1"
```

---

## 1. Install the toolchain and run pre-deploy checks (workstation)

Working dir: repo root. These checks gate a deploy; they do not deploy anything.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

.\.venv\Scripts\ruff.exe check src tests lambda scripts   # lint
.\.venv\Scripts\mypy.exe                                   # types
.\.venv\Scripts\python.exe -m pytest tests\unit            # pure-logic unit tests
```

Expected: lint and types clean; unit tests pass. These exercise password
generation, the alternating-users mapping, certificate expiry logic, the policy
checker, audit parsing, and secret redaction — none of which need AWS. The full
rotation lifecycle is verified on AWS in section 5.

---

## 2. Build the rotation Lambda package

Working dir: repo root. Produces the zip Terraform deploys, vendoring the Linux
psycopg wheel for the Lambda runtime (works from any OS).

```powershell
.\.venv\Scripts\python.exe scripts\build_lambda.py --python-version 312 --arch x86_64
```

Verify the package contains `handler.py`, `secrets_rotation/`, and `psycopg*`
under `terraform/modules/rotation-lambda/build/package/`.

---

## 3. Provision networking (apply FIRST)

The rotation Lambda runs in private subnets to reach RDS, and reaches the
Secrets Manager and CloudWatch Logs APIs over the internet via a **NAT
gateway** (the private subnets have no public IPs, but a single NAT gateway
provides outbound egress). You have two options:

### Option A (recommended): use the network bootstrap environment

Working dir: `terraform/environments/network`. This creates the VPC, public and
private subnets (2 AZs), an internet gateway, a **single NAT gateway** (one EIP,
one AZ), and a free S3 gateway endpoint, with its own state so the network has
an independent lifecycle. `enable_nat = true` by default.

> **NAT gateway is chargeable** (not free-tier): ~$32/mo plus ~$0.045/GB data
> processed in us-east-1. It is what lets the private subnets reach public AWS
> APIs and public container registries without per-service VPC endpoints. See
> `costs.md`.

```powershell
Copy-Item terraform.tfvars.example terraform.tfvars
# Edit: aws_region, availability_zones (2+ in your region), vpc_cidr.
terraform init
terraform plan -out tfplan      # review
terraform apply tfplan
terraform output                # vpc_id, private_subnet_ids
```

The `dev` environment reads these outputs automatically — you do not copy the
ids by hand. See `terraform/environments/network/README.md`.

### Option B: bring your own VPC

If you already have a VPC with two private subnets in different AZs, skip the
network environment and set `use_network_remote_state = false` plus `vpc_id` /
`private_subnet_ids` in the dev tfvars (section 4a). Those subnets must have
outbound internet egress (a NAT gateway, or equivalent) so the Lambda reaches
Secrets Manager + CloudWatch Logs and the EKS nodes can pull public images.

Either way, the `dev` environment creates the Lambda's security group and wires
the rest: the RDS security group admits PostgreSQL only from the Lambda's
security group, the Lambda attaches to the private subnets, and the secret's
`db_host` is set to the RDS endpoint automatically. The database is never public.

---

## 4. Deploy AWS resources with Terraform (CHARGEABLE on apply)

Working dir: `terraform/environments/dev`.

### 4a. Configure

```powershell
Copy-Item terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars:
#   aws_region, owner_tag
#   create_database = true
# Networking source A (default): use_network_remote_state = true and the
#   network_state_* values point at the network environment's state.
# Networking source B: set use_network_remote_state = false and supply
#   vpc_id / private_subnet_ids.
# db_host is wired from the RDS endpoint automatically — no two-phase apply.
```

Configure the encrypted S3 backend in `main.tf` for shared/team state (see
`terraform-state.md`). If you used Option A with S3 state, set
`network_state_backend = "s3"` and `network_state_config` in the dev tfvars so
dev reads the network state from S3. For a solo disposable test, local state is
acceptable (gitignored) — but the database bootstrap password will be in that
state file, so treat it as sensitive and destroy when done.

### 4b. Plan and apply

```powershell
terraform init
terraform plan -out tfplan      # REVIEW the plan
terraform apply tfplan
```

This creates: 3 Secrets Manager secrets (master, database, external-api), the
rotation Lambda + least-privilege IAM role, the CloudWatch log group + failure
and staleness alarms, the native rotation schedule, and (with
`create_database = true`) a private RDS PostgreSQL instance.

### 4c. Outputs

```powershell
terraform output      # ARNs and names only — never secret values
```

### 4d. Seed the external-API secret value

Terraform leaves the API secret as a placeholder (an API key is minted at the
provider, not by Terraform). Seed a synthetic value for the demo:

```powershell
# Working dir: repo root
.\.venv\Scripts\python.exe scripts\create_dummy_secret.py --region us-east-1 --env dev --app myapp
```

---

## 5. Test a real rotation on AWS

Working dir: repo root. Requires section 4 applied with RDS.

```powershell
# Trigger a managed rotation of the database secret:
aws secretsmanager rotate-secret --secret-id dev/myapp/database

# Verify staging labels advanced (prints NO secret values):
.\.venv\Scripts\python.exe scripts\verify_rotation.py --secret-id dev/myapp/database
```

Expect `RotationEnabled = True`, a recent `LastRotatedDate`, and both
`AWSCURRENT` and `AWSPREVIOUS` labels present.

Run the AWS integration test suite (drives rotation and authenticates the
rotated credential against RDS):

```powershell
$env:RUN_AWS_INTEGRATION = "1"
$env:SECRET_ID = "dev/myapp/database"
.\.venv\Scripts\python.exe -m pytest -m integration -rs
```

Inspect the rotation logs (structured, redacted — no secret values):

```powershell
aws logs tail /aws/lambda/dev-myapp-db-rotation --since 15m
```

---

## 6. Kubernetes integration on EKS (Terraform-managed)

Working dir: `terraform/environments/eks`. The entire Kubernetes layer — the EKS
cluster, its OIDC provider, a managed node group, KMS envelope encryption, the
IRSA reader role (`dev-myapp-eso-reader`, read-only on `dev/myapp/*`), the
External Secrets Operator (ESO) Helm release, and every in-cluster object
(namespaces, service account, SecretStore, ExternalSecret, RBAC, sample app) —
is provisioned by **one Terraform environment**. No `eksctl`, no manual `helm
install`, no hand-run `kubectl apply`. One `terraform apply` builds it; one
`terraform destroy` (section 8) removes all of it, including the in-cluster
objects, so nothing is orphaned.

The canonical YAML in `kubernetes/` stays authoritative: Terraform applies those
files verbatim via `kubectl_manifest`. The only object reconstructed in HCL is
the `myapp-secrets` service account, so the real IRSA role ARN is injected in
place of the `<ACCOUNT_ID>` placeholder.

> **EKS is chargeable** — control plane ~$0.10/hr plus a 2 × t3.medium on-demand
> node group. Review `costs.md` and keep the node group small (or a single
> t3.small) for a disposable test. Apply the **network** environment (section 3)
> first; the eks env reads its VPC/subnet outputs.
>
> **NAT egress (no mirror needed):** the VPC has a single NAT gateway, so worker
> nodes in the private subnets have normal outbound internet access. They
> bootstrap by pulling the kubelet/CNI images and join the cluster over NAT, and
> ESO pulls its images directly from the public registry
> (`oci.external-secrets.io`) — there is **no ECR image mirror step**. The only
> VPC endpoint kept is the free S3 gateway endpoint. If you bring your own VPC,
> just make sure the private subnets have a NAT gateway (or equivalent egress).
>
> **ESO STS note:** the Helm release sets `AWS_STS_REGIONAL_ENDPOINTS=regional`
> and `AWS_REGION=us-east-1` on the controller so IRSA
> `AssumeRoleWithWebIdentity` uses the in-region STS endpoint. This is retained
> as a benign best-practice and needs no action from you.

**Single apply — no pre-steps.** With NAT in place the entire EKS stack comes up
in one `terraform apply`; there is nothing to mirror first. Your AWS account
(`<AWS_ACCOUNT_ID>`) and region (`us-east-1`) are fixed for this stack:

```powershell
cd terraform\environments\eks
Copy-Item terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars if needed (node sizing, network-state backend). Note the
# network-state default DIVERGES from dev: this env defaults to S3 remote state.
# If you applied the network env with LOCAL state, set:
#   network_state_backend = "local"
#   network_state_config   = { path = "../network/terraform.tfstate" }

terraform init
terraform plan -out tfplan      # REVIEW the plan — nothing is created until apply
terraform apply tfplan          # builds cluster, node group, ESO, and all in-cluster objects
```

The cluster takes ~12–15 minutes to create, plus the node group and the ESO
Helm release. If the apply is interrupted mid-build, re-running `terraform apply`
reconciles in place. Use `terraform apply -replace=helm_release.external_secrets`
only if a stuck `pending-install` state persists. See the eks env README for the
full recovery note.

The three in-cluster providers (`kubernetes`, `helm`, `kubectl`) authenticate to
the cluster via the `aws_eks_cluster` / `aws_eks_cluster_auth` data sources, so
the whole stack comes up in a **single apply**: Terraform creates the cluster
first, then configures those providers and applies the Helm release and
manifests. Explicit `depends_on` edges keep ESO's CRDs installed before the
`SecretStore` / `ExternalSecret` custom resources apply.

Read back the key values and point kubectl at the cluster for inspection:

```powershell
terraform output                # cluster_name, reader_role_arn, oidc_provider_arn, kms_key_arn
aws eks update-kubeconfig --name dev-myapp-eks --region us-east-1
# or, name-agnostic:
# aws eks update-kubeconfig --name $(terraform output -raw cluster_name) --region us-east-1
```

The cluster is named `dev-myapp-eks` (from the `${environment}-${app_name}`
prefix), replacing the old `eksctl`-created `secrets-demo` name.

### Verify the stack is healthy after apply

Confirm ESO authenticated to AWS, synced the secret, and the sample app pulled
its public image over NAT and started:

```bash
# ESO pods Running, pulling from the PUBLIC registry (image is oci.external-secrets.io, not an ECR URL)
kubectl -n external-secrets get pods

# IRSA/STS healthy: store Ready, secret synced, target secret created with 4 keys
kubectl -n myapp get secretstore aws-secretsmanager    # expect READY = True
kubectl -n myapp get externalsecret myapp-database      # expect READY = True / SecretSynced
kubectl -n myapp get secret myapp-database              # exists: DB_USERNAME, DB_PASSWORD, DB_HOST, DB_NAME

# Sample app pulls busybox:1.36 from Docker Hub via NAT (NO ImagePullBackOff)
kubectl -n myapp get deploy,pods                        # myapp pod 1/1 Running
```

If ESO still reports a `WebIdentityErr` STS timeout, the NAT gateway or the
private-subnet default route is missing — confirm
`aws ec2 describe-nat-gateways` shows one `available` NAT and the private route
table has `0.0.0.0/0` → that NAT.

### Verify sync + refresh after rotation

```bash
kubectl get externalsecret -n myapp          # expect SecretSynced = True
kubectl logs -n myapp deploy/myapp -f         # prints the configured DB user
aws secretsmanager rotate-secret --secret-id dev/myapp/database
# Within refreshInterval (1m) the mounted file updates; the env var copy needs
# a pod restart: kubectl rollout restart deploy/myapp -n myapp
```

---

## 7. CI/CD

Push to GitHub. The `quality`, `terraform`, and `package` jobs run on every PR
(no AWS, no setup needed). The `deploy-dev` job is the only one that touches AWS,
and it needs a one-time bootstrap.

### 7a. Bootstrap the CI deploy role (one time, local)

The deploy role lives in its **own** Terraform environment,
`terraform/environments/cicd`, so it is not managed by the `dev` apply it
authorizes (that would be circular). Apply it once from your workstation with
elevated credentials:

```powershell
cd terraform\environments\cicd
Copy-Item terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars: github_org + github_repo are required. Adjust
# allowed_refs (the branch you dispatch from) and aws_region if needed.
# If your AWS account already has a GitHub OIDC provider, set
#   create_oidc_provider = false  and  existing_oidc_provider_arn = "arn:..."

terraform init
terraform plan -out tfplan      # review
terraform apply tfplan
terraform output github_setup_hint   # prints the exact GitHub values to set
```

This creates the GitHub Actions OIDC provider (unless reused) and a
least-privilege IAM role scoped to exactly what a `dev` apply needs. See
`terraform/environments/cicd/README.md` and `cicd.md`.

> Prerequisite: the state bucket(s) exist and the **network** env is applied —
> the `dev` apply CI runs reads the network remote state.

### 7b. Wire GitHub (one time)

Using the `github_setup_hint` output:

- Repo **secret** `AWS_DEPLOY_ROLE_ARN` = the `deploy_role_arn` output.
- Repo **variable** `AWS_REGION` (a *variable*, not a secret).
- A GitHub **environment** named `dev` with required reviewers (the approval gate).

### 7c. Deploy

Run the workflow manually (`workflow_dispatch`) with `deploy_dev = true`, from a
branch listed in `allowed_refs`. It assumes the role via OIDC and applies the
`dev` environment. See `cicd.md`.

---

## 8. Teardown (stop the charges)

Destroy in reverse order: **EKS first, then the app, then (if you created it)
the network**. The eks and dev environments both read the network environment's
VPC/subnet outputs, so destroying them before the network avoids orphaning
resources that depend on the VPC. The three environments have independent
state, so each `terraform destroy` is scoped to its own layer.

```powershell
# 1. EKS layer (removes the cluster, node group, OIDC provider, KMS key,
#    IAM roles, the ESO release, and every in-cluster object)
cd terraform\environments\eks
terraform destroy
```

Run the destroy **while the cluster still exists** — the `kubernetes`/`helm`/
`kubectl` providers need a cluster token to delete the in-cluster objects, which
Terraform tears down first (manifests, then node group, then cluster, then
OIDC/KMS/IAM).

**Half-destroy recovery:** if a destroy is interrupted after the cluster is gone
but with in-cluster resources still in state, the providers can no longer get a
token and re-running destroy fails to plan. Remove **only** the orphaned
in-cluster entries from state (they died with the cluster), then re-run destroy.
Preview exactly which addresses are safe to remove:

```powershell
terraform state list | Select-String '^(helm_release|kubernetes_service_account_v1|kubectl_manifest)\.'
```

Safe to `terraform state rm` (in-cluster objects, already gone with the cluster):

- `helm_release.external_secrets`
- `kubernetes_service_account_v1.myapp_secrets`
- every `kubectl_manifest.*` address (`kubectl_manifest.namespaces[*]`,
  `.rbac[*]`, `.secretstore`, `.externalsecret`, `.sample_app`)

NEVER `state rm` these — they are real AWS resources and removing them from
state orphans them in AWS (the opposite of a clean teardown):

- anything under `module.eks.*` (cluster, node group, OIDC provider, KMS key,
  KMS alias, cluster/node IAM roles + attachments)
- anything under `module.eks_irsa.*` (the reader role + inline policy)

Known residue after an EKS destroy: AWS keeps the control-plane log group
`/aws/eks/dev-myapp-eks/cluster`, and the KMS key enters its 7-day deletion
window rather than deleting immediately (see `costs.md`). Confirm the cluster is
gone with `aws eks list-clusters --region us-east-1` (expect `dev-myapp-eks`
absent).

```powershell
# 2. App layer
cd terraform\environments\dev
terraform destroy                 # removes secrets, Lambda, RDS, monitoring, SGs
```

```powershell
# repo root — irreversible secret delete (clears the recovery window)
.\.venv\Scripts\python.exe scripts\cleanup.py --force
```

```powershell
# 3. Network layer (only if you used Option A in section 3)
cd terraform\environments\network
terraform destroy                 # removes VPC, subnets, IGW, NAT gateway, EIP, S3 endpoint
```

> **Destroy the network layer to stop NAT charges.** The NAT gateway bills
> ~$32/mo plus data processing for as long as it exists, even idle. If you tear
> down eks and dev but leave the network environment up, the NAT keeps billing.

```powershell
# 4. CI/CD identity (only if you bootstrapped it in section 7a, and only when
#    you no longer want the GitHub Actions deploy pipeline)
cd terraform\environments\cicd
terraform destroy                 # removes the deploy role (+ OIDC provider if it created one)
```

> The `cicd` env carries no running/billable resources (IAM only), so there is
> no cost reason to destroy it — do so only to revoke CI's deploy access. If you
> reused an existing OIDC provider (`create_oidc_provider = false`), destroy
> removes only the role, not the shared provider.

See `costs.md` for what can keep billing after a naive teardown (secret recovery
windows, CloudWatch log groups, the Terraform state bucket, RDS snapshots, and
the NAT gateway).
