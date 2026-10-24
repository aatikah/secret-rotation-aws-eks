"""Verify the current rotation state of a secret (live AWS).

Reports the version staging labels, whether rotation is enabled, and the
configured rotation interval — WITHOUT printing any secret value. Useful after
triggering a rotation to confirm AWSCURRENT advanced and AWSPREVIOUS exists for
recovery.

Usage (requires AWS credentials):
    python scripts/verify_rotation.py --secret-id dev/myapp/database
"""

from __future__ import annotations

import argparse

import boto3


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secret-id", required=True)
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    client = boto3.client("secretsmanager", region_name=args.region)
    meta = client.describe_secret(SecretId=args.secret_id)

    print(f"Secret: {meta['Name']}")
    print(f"  RotationEnabled : {meta.get('RotationEnabled', False)}")
    rules = meta.get("RotationRules", {})
    if rules:
        print(f"  Interval (days) : {rules.get('AutomaticallyAfterDays', 'n/a')}")
    print(f"  LastRotatedDate : {meta.get('LastRotatedDate', 'never')}")
    print("  Version staging labels:")
    for version, stages in meta.get("VersionIdsToStages", {}).items():
        print(f"    {version[:12]}... -> {', '.join(stages)}")
    print("\n(No secret values are retrieved or printed by this script.)")


if __name__ == "__main__":
    main()
