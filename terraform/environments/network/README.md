# Network bootstrap environment

Apply this **first**. It creates the VPC, public and private subnets (2 AZs), an
internet gateway, and a single **NAT gateway** that gives the private subnets
outbound internet egress — so the rotation Lambda reaches Secrets Manager and
CloudWatch Logs and the EKS nodes pull public images. The `dev` environment
reads this environment's outputs automatically.

## What it creates

- A VPC (default `10.20.0.0/16`).
- Public subnets (host the NAT gateway) and private subnets across your chosen
  AZs (Lambda + RDS + EKS nodes live in the private subnets).
- An internet gateway and a single **NAT gateway** (one EIP, one AZ) providing
  egress for the private subnets (`enable_nat = true` by default).
- A free **S3 gateway endpoint** (no hourly charge).

> The NAT gateway replaced the previous per-service interface VPC endpoints
> (secretsmanager, logs, ecr.api, ecr.dkr, sts, ec2). One NAT provides egress to
> all public AWS APIs and container registries, which removed the ESO image
> mirror and the no-NAT workarounds. The only endpoint kept is the free S3
> gateway endpoint.

## Apply

Working dir: `terraform/environments/network`.

```powershell
Copy-Item terraform.tfvars.example terraform.tfvars
# Edit: aws_region, availability_zones (2+ in your region), vpc_cidr.

terraform init
terraform plan -out tfplan     # review
terraform apply tfplan
terraform output               # vpc_id, private_subnet_ids, ...
```

For shared/team use, configure the S3 backend block in `main.tf` so the `dev`
environment can read this state from S3 (set `network_state_backend = "s3"` and
`network_state_config` in the dev tfvars to match). For a solo throwaway test,
local state is fine (the dev env defaults to reading `../network/terraform.tfstate`).

## Then deploy the app

Go to `terraform/environments/dev`, keep `use_network_remote_state = true`, and
`terraform apply`. It picks up this environment's VPC and subnets automatically.
See `../../../docs/deployment.md`.

## Teardown order

Destroy the app first, then the network:

```powershell
# in environments/dev
terraform destroy
# then in environments/network
terraform destroy
```

Cost: the VPC, subnets, route tables, IGW, and the S3 gateway endpoint are free.
The **NAT gateway** is the main cost (~$32/month + ~$0.045/GB processed in
us-east-1) and bills for as long as this environment exists — destroy it to stop
the charge. See `../../../docs/costs.md`.
