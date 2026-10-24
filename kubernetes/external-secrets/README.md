# External Secrets Operator (ESO) integration

Syncs AWS Secrets Manager values into native Kubernetes Secrets so workloads
consume them without talking to AWS directly.

## Why ESO (recap)

ESO *synchronizes* a Secrets Manager secret into a Kubernetes `Secret` object
that any Deployment can consume via `envFrom` or a volume. This is the primary
approach for the project; the Secrets Store CSI Driver (which *mounts* material
into a pod volume) is the alternative. See `../../docs/architecture.md`.

## How ESO and these manifests are installed (Terraform)

ESO and all of these manifests are installed by the Terraform EKS environment,
`terraform/environments/eks` — not by a hand-run `helm install` or `kubectl
apply`. That environment:

- creates the EKS cluster, its OIDC provider, a managed node group, and KMS
  envelope encryption (`terraform/modules/eks`);
- creates the read-only IRSA role `dev-myapp-eso-reader`
  (`terraform/modules/eks-irsa`);
- installs the ESO Helm release (chart `external-secrets/external-secrets`,
  repo `https://charts.external-secrets.io`, version `0.16.2`,
  `installCRDs=true`), pulling its default public operator images from
  `oci.external-secrets.io` directly over the VPC's NAT gateway — no private ECR
  mirror or image overrides. The release also sets
  `AWS_STS_REGIONAL_ENDPOINTS=regional` and `AWS_REGION=us-east-1` on the
  controller so IRSA `AssumeRoleWithWebIdentity` uses the in-region STS endpoint;
- applies the YAML files in this folder (and `../policies/rbac.yaml`,
  `../sample-app/deployment.yaml`) **verbatim** via `kubectl_manifest`.

These YAML files stay **canonical** — Terraform reads them as-is. The only
object reconstructed in HCL is the `myapp-secrets` service account (as
`kubernetes_service_account_v1`), so the real IRSA role ARN from the `eks-irsa`
module is injected in place of the `<ACCOUNT_ID>` placeholder in
`10-serviceaccount-irsa.yaml`.

Deploy and inspect:

```bash
# From terraform/environments/eks: terraform init && terraform apply
# (see ../../docs/deployment.md section 6)
aws eks update-kubeconfig --name dev-myapp-eks --region us-east-1

# Verify the operator is running and the ExternalSecret reconciled:
kubectl get pods -n external-secrets
kubectl get crds | grep external-secrets.io
kubectl get externalsecret -n myapp
kubectl get secret myapp-database -n myapp -o jsonpath='{.data}' | wc -c  # size only, never print values
```

## Authentication (EKS, IRSA / Pod Identity)

The service account (`10-serviceaccount-irsa.yaml`) is annotated with an IAM
role that has **read-only** access to `dev/myapp/*`. The `SecretStore` uses
`auth.jwt.serviceAccountRef` so the pod assumes that role via the cluster's OIDC
provider — **no AWS keys live in the cluster.** The role (`dev-myapp-eso-reader`)
is created by the `terraform/modules/eks-irsa` module and bound to the cluster
OIDC provider and the `myapp:myapp-secrets` service account; the
`terraform/environments/eks` environment injects its ARN into the service
account annotation automatically. The `<ACCOUNT_ID>` placeholder in the YAML is
the human-readable template — Terraform supplies the real ARN at apply time.

## Verifying rotation propagation

1. Note the current synced value's data hash (never the value):
   `kubectl get secret myapp-database -n myapp -o jsonpath='{.metadata.resourceVersion}'`
2. Trigger a rotation in AWS Secrets Manager (`aws secretsmanager rotate-secret`).
3. Within `refreshInterval` (1m here), ESO updates the Kubernetes Secret; the
   resourceVersion changes.
4. The sample app reading the **mounted file** picks up the new username without
   a restart; the **env var** copy does not change until the pod restarts — see
   `../sample-app/`.

## Security

- RBAC (`../policies/rbac.yaml`) restricts the app SA to reading only its own
  Secret.
- Enable **encryption at rest** for Secrets in the cluster (EKS KMS envelope
  encryption).
- Namespaces isolate the operator, store, and app.
- Never `kubectl apply` a populated Secret manifest from git — ESO owns the
  Secret's contents.
