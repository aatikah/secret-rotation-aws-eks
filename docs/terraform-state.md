# Terraform state risks and secure state management

## Why state is sensitive here

Terraform state records the full value of every managed resource, including
attributes marked sensitive. In this project the `random_password` resources
(the bootstrap master and application passwords) land in state **in plaintext**.
Anyone who can read the state file can read those bootstrap passwords.

This is unavoidable for the initial bootstrap value — but it is mitigated by
design:

1. **The bootstrap value is short-lived.** The very first rotation replaces the
   application password, and `ignore_changes = [secret_string]` hands ongoing
   ownership of the value to Secrets Manager. State no longer reflects the live
   credential after the first rotation.
2. **State is never committed.** `.gitignore` blocks `*.tfstate*` and
   `.terraform/`.
3. **Secret values are never exposed as outputs.** Outputs are ARNs/names only.

## Secure backend

Use an encrypted remote backend with locking rather than local state:

```hcl
backend "s3" {
  bucket         = "your-tfstate-bucket"   # SSE-KMS enabled, versioned, private
  key            = "secrets-rotation/dev/terraform.tfstate"
  region         = "us-east-1"
  dynamodb_table = "your-tf-locks"         # state locking
  encrypt        = true
}
```

Recommended bucket hardening:

- Default encryption with a KMS key (not just SSE-S3) and `BucketKeyEnabled`.
- Block all public access.
- Versioning on (so a corrupted/compromised state can be rolled back).
- A bucket policy restricting access to the deploy role / specific principals.
- DynamoDB table for state locking to prevent concurrent-apply corruption.

## Local state for throwaway testing

For a quick, isolated dev test you may run with local state (the default when
the backend block is commented out). The state file stays on your machine and
is gitignored. Treat it as sensitive and delete it when done:

```powershell
terraform destroy
Remove-Item terraform.tfstate* -Force
```

## Avoid plaintext credentials in state unnecessarily

- Do not pass real credentials as Terraform variables or hardcode them in
  resources. Let Secrets Manager + rotation own the live values.
- Do not add `output` blocks that emit secret values.
- Prefer `ephemeral`/write-only patterns where your provider version supports
  them for values that must transit Terraform.
