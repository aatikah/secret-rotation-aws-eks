# Prerequisites

This project deploys, tests, and simulates on AWS. Your workstation runs only
the developer toolchain (install, lint, type check, pure-logic unit tests) plus
the AWS/Kubernetes CLIs used to deploy and operate the stack.

| Tool | Why | Needed for |
|---|---|---|
| Python 3.11+ | library, CLI, unit tests, Lambda packaging | always |
| Git | version control | always |
| AWS CLI v2 (+ credentials) | deploy, trigger rotations, inspect logs | always |
| Terraform | provision AWS infrastructure | always |
| kubectl | manage the EKS workloads | Kubernetes stage |
| Helm | install External Secrets Operator | Kubernetes stage |
| eksctl | create the EKS cluster + IRSA service accounts | Kubernetes stage |

## Verify what you already have

PowerShell (Windows):

```powershell
python --version      # need 3.11+
git --version
aws --version
terraform -version
kubectl version --client   # Kubernetes stage
helm version               # Kubernetes stage
eksctl version             # Kubernetes stage
```

Git Bash / macOS / Linux: the same commands work (use `python3` if `python` is
not on PATH).

## Install (Windows, winget)

```powershell
winget install --id Python.Python.3.12 -e
winget install --id Git.Git -e
winget install --id Amazon.AWSCLI -e
winget install --id Hashicorp.Terraform -e
winget install --id Kubernetes.kubectl -e
winget install --id Helm.Helm -e
winget install --id Weaveworks.eksctl -e
```

## Install (macOS / Linux)

```bash
#   macOS:  brew install python git awscli terraform kubectl helm eksctl
#   Debian: apt-get install -y python3 python3-venv git
# AWS CLI v2 (Linux x86_64):
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip awscliv2.zip && sudo ./aws/install
# Terraform, kubectl, helm, eksctl: follow the official install docs for your OS.
```

## AWS credentials

Manual runs use your local AWS profile; CI uses GitHub Actions OIDC federation
(no long-lived keys):

```powershell
aws configure                 # sets ~/.aws/credentials for local use
aws sts get-caller-identity   # confirm you are authenticated
```

Do not store long-lived AWS access keys in repository secrets. The CI stage
provisions an OIDC identity provider and a narrowly-scoped deploy role instead
(see `cicd.md` and the `cicd-identity` Terraform module).
