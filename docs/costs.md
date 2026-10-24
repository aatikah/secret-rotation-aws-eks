# Cost awareness

Read this before running `terraform apply`. Figures are rough order-of-magnitude
estimates for the `us-east-1` region to set expectations — **check the current
AWS pricing pages for exact, current numbers in your region.** Content on
pricing changes often; verify before relying on it.

## Control-plane layer (secrets + Lambda + monitoring)

The non-database resources are near-zero cost:

| Resource | Approx. cost | Notes |
|---|---|---|
| Secrets Manager secrets (3) | ~$0.40/secret/month | Prorated; plus a tiny per-10k-API-call charge |
| Lambda (rotation) | ~free | Well within the free tier for occasional rotations |
| CloudWatch Logs | pennies | Bounded by `log_retention_days` (default 90) |
| CloudWatch alarms | ~$0.10/alarm/month | 1–2 alarms |

Expect well under a few dollars per month for this layer. If you only need to
exercise secret/rotation plumbing against an existing database, set
`create_database = false` and point `db_host` at it to avoid the RDS cost below.

## Database layer — the main cost driver (`create_database = true`)

A full deploy includes a private `db.t4g.micro` single-AZ PostgreSQL instance
with 20 GB storage:

| Resource | Approx. cost | Notes |
|---|---|---|
| RDS db.t4g.micro | ~$12–15/month if left running | Hourly; destroy when done |
| RDS storage (20 GB gp) | ~$2–3/month | |
| Data transfer | usually negligible | Private subnet, no public egress |

**The disposable database is meant to be created, tested, and destroyed the
same day.** Leaving it running accrues charges.

## EKS layer (`environments/eks`) — chargeable while running

The Kubernetes stack is the other main cost driver. It is created and destroyed
by one Terraform environment (`environments/eks`), so a single `terraform
destroy` removes the cluster and node group cleanly.

| Resource | Approx. cost | Notes |
|---|---|---|
| EKS control plane | ~$0.10/hour (~$73/month) | Billed per cluster-hour whether or not workloads run |
| Managed node group (2 × t3.medium, on-demand) | ~$0.08–0.09/hour (~$60/month) | The default. Drop to a single `t3.small` (`node_instance_type = "t3.small"`, `node_desired_size = 1`, `node_min_size = 1`) to roughly quarter this |
| EBS volumes (node root disks) | a few $/month | One gp3 volume per node |
| KMS key (secrets envelope encryption) | ~$1/month + per-request | One customer-managed key; key rotation enabled |
| Control-plane logs (CloudWatch) | pennies–small | `api`/`audit`/`authenticator` log types |

**The EKS stack is meant to be created, demonstrated, and destroyed the same
day.** Leaving the control plane and node group running accrues the hourly
charges above. `terraform destroy` in `environments/eks` removes the cluster,
node group, OIDC provider, KMS key (into its deletion window), and IAM roles.

## Network layer (`environments/network`)

| Resource | Approx. cost | Notes |
|---|---|---|
| VPC, subnets, route tables, IGW | free | no hourly charge |
| NAT gateway (single, `enable_nat = true`) | ~$32/month + ~$0.045/GB processed | One NAT in one AZ gives the private subnets outbound egress; the main network-layer cost. Bills while it exists, even idle |
| S3 gateway endpoint | free | no hourly charge; private path to S3 (e.g. ECR image layers) |

A single NAT gateway gives the private-subnet Lambda and the EKS worker nodes
outbound access to all public AWS APIs (Secrets Manager, CloudWatch Logs, STS,
ECR, EC2) and public container registries. It replaced the earlier set of
per-service interface VPC endpoints (secretsmanager, logs, ecr.api, ecr.dkr, sts,
ec2): one NAT is simpler to reason about and removed the ESO image-mirror
workaround, at the cost of the ~$32/month gateway charge. The S3 gateway
endpoint is free and kept. To trim cost on a pure rotation-only (no-EKS)
deployment you could swap back to interface endpoints, but the project now
standardizes on NAT.

## Things that keep costing after a naive teardown

- **Secrets scheduled for deletion** still exist (and may bill) until the
  recovery window elapses. Use `scripts/cleanup.py --force` for immediate,
  irreversible deletion when you are sure.
- **CloudWatch log groups** persist with their retention unless deleted. This
  includes the EKS control-plane log group `/aws/eks/dev-myapp-eks/cluster`,
  which AWS keeps after the cluster is destroyed — delete it manually if you do
  not want it to linger.
- **The EKS KMS key** does not delete immediately on `terraform destroy`; it
  enters a 7-day deletion window (and bills ~$1/month until it finishes). Cancel
  the deletion if you need it back, or let the window elapse.
- **Terraform state bucket / lock table** (if you created them) are separate
  resources with their own small ongoing cost.
- **RDS final snapshots** — the module sets `skip_final_snapshot = true`, so no
  snapshot is retained; adjust if you want one (it would bill for storage).

- **The NAT gateway** keeps billing (~$32/month + data) until the network
  environment is destroyed. Destroy `environments/network` after the app.

## Clean teardown (reverse order)

```powershell
# 1. EKS layer (if you created it) — destroy while the cluster still exists
cd terraform\environments\eks
terraform destroy

# 2. App layer
cd ..\dev
terraform destroy

# Remove any secrets still in the recovery window, if desired:
python ..\..\..\scripts\cleanup.py --force

# 3. Network layer (if you created it)
cd ..\network
terraform destroy
```
