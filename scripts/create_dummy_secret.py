"""Seed the demo API-credential value in AWS Secrets Manager.

The database and master secrets are created by Terraform (the `secrets-manager`
module) with generated bootstrap passwords. Terraform intentionally leaves the
external-API secret's value as a placeholder, because an API key is minted at
the provider, not by Terraform. This script sets an initial synthetic API key
value for the mock-API rotation demo.

Runs against REAL AWS using your current credentials. Values are generated with
a CSPRNG and are NEVER printed — only the secret name and version id.

Usage (from repo root, requires AWS credentials):
    python scripts/create_dummy_secret.py
    python scripts/create_dummy_secret.py --region us-east-1 --env dev --app myapp
"""

from __future__ import annotations

import argparse
import json
import secrets as _secrets

import boto3


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--env", default="dev")
    parser.add_argument("--app", default="myapp")
    args = parser.parse_args()

    api_name = f"{args.env}/{args.app}/external-api"
    client = boto3.client("secretsmanager", region_name=args.region)

    # A synthetic initial key for the mock provider. In a real integration the
    # key would be minted at the provider; this seeds the demo starting point.
    initial_key = "key-" + _secrets.token_hex(16)
    resp = client.put_secret_value(
        SecretId=api_name,
        SecretString=json.dumps({"api_key": initial_key, "provider": "mock"}),
    )
    print("Seeded API secret value (value hidden):")
    print(f"  {api_name}  version={resp['VersionId']}")


if __name__ == "__main__":
    main()
