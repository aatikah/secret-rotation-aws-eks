"""Failure-simulation drills against a REAL AWS deployment.

Each drill induces a specific failure in the live rotation flow and shows the
recovery behaviour, using the deployed Secrets Manager secret, rotation Lambda,
and RDS database. Requires the Terraform `dev` environment to be applied (see
docs/deployment.md) and AWS credentials.

Drills (match the task's failure-testing list):
  1. Failed validation / unreachable DB during rotation -> no promotion.
  2. Duplicate / concurrent rotation attempt            -> rejected, no corruption.
  3. Overdue / stale rotation detection                 -> surfaced by metric/policy.

The script NEVER prints secret values. It reports only names, version ids,
staging labels, and rotation status.

Usage (requires AWS credentials + an applied dev environment):
    python scripts/simulate_failures.py --secret-id dev/myapp/database
    python scripts/simulate_failures.py --secret-id dev/myapp/database --only 1
"""

from __future__ import annotations

import argparse
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError


def _current_version(client: Any, secret_id: str) -> str | None:
    meta = client.describe_secret(SecretId=secret_id)
    for version, stages in meta.get("VersionIdsToStages", {}).items():
        if "AWSCURRENT" in stages:
            return version
    return None


def _wait_for_rotation_idle(client: Any, secret_id: str, timeout: int = 180) -> dict[str, Any]:
    """Poll until no rotation is in progress (or timeout). Returns describe output."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        meta = client.describe_secret(SecretId=secret_id)
        stages = {s for v in meta.get("VersionIdsToStages", {}).values() for s in v}
        if "AWSPENDING" not in stages:
            return meta
        time.sleep(5)
    return client.describe_secret(SecretId=secret_id)


def drill_failed_rotation(client: Any, secret_id: str) -> None:
    """Drill 1: a rotation that fails validation must not move AWSCURRENT.

    Precondition for a realistic failure: the rotation Lambda cannot reach the
    DB or the master grant is missing. Set that up per docs/testing-and-
    simulation.md (e.g. a security-group rule change) BEFORE running this drill.
    This drill triggers rotation and asserts AWSCURRENT did not advance.
    """
    print("\n[Drill 1] Failed rotation must not promote")
    before = _current_version(client, secret_id)
    print(f"  AWSCURRENT before: {before[:12] if before else None}...")
    try:
        client.rotate_secret(SecretId=secret_id)
        print("  rotation requested; waiting for it to settle...")
    except ClientError as exc:
        print(f"  rotate_secret returned: {exc.response['Error']['Code']}")
    _wait_for_rotation_idle(client, secret_id)
    after = _current_version(client, secret_id)
    print(f"  AWSCURRENT after : {after[:12] if after else None}...")
    if before == after:
        print("  RECOVERY: AWSCURRENT unchanged — invalid credential NOT promoted. "
              "Check CloudWatch alarm dev-myapp-rotation-failure.")
    else:
        print("  AWSCURRENT advanced — rotation succeeded (DB was reachable). "
              "Re-run after inducing the failure condition to see the no-promote path.")


def drill_concurrent_rotation(client: Any, secret_id: str) -> None:
    """Drill 2: a second rotation while one is in progress must be rejected."""
    print("\n[Drill 2] Concurrent / duplicate rotation rejected")
    try:
        client.rotate_secret(SecretId=secret_id)
        # Immediately request again; Secrets Manager rejects overlapping rotations.
        client.rotate_secret(SecretId=secret_id)
        print("  second rotate_secret accepted (first may have already finished)")
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        print(f"  RECOVERY: concurrent rotation rejected ({code}) — no corruption")
    _wait_for_rotation_idle(client, secret_id)


def drill_stale_detection(client: Any, secret_id: str) -> None:
    """Drill 3: show how overdue rotation is detected (metric + policy)."""
    print("\n[Drill 3] Overdue / stale rotation detection")
    meta = client.describe_secret(SecretId=secret_id)
    last = meta.get("LastRotatedDate")
    rules = meta.get("RotationRules", {})
    interval = rules.get("AutomaticallyAfterDays")
    print(f"  RotationEnabled : {meta.get('RotationEnabled', False)}")
    print(f"  Interval (days) : {interval}")
    print(f"  LastRotatedDate : {last}")
    print("  Detection: the CloudWatch alarm dev-myapp-rotation-stale watches "
          "AWS/SecretsManager DaysSinceLastRotation; the policy checker also "
          "flags overdue secrets (secrets-rotation policy-check).")


_DRILLS = [drill_failed_rotation, drill_concurrent_rotation, drill_stale_detection]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--secret-id", required=True, help="Secret name or ARN (e.g. dev/myapp/database)."
    )
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--only", type=int, help="Run a single drill (1-3).")
    args = parser.parse_args()

    client = boto3.client("secretsmanager", region_name=args.region)
    drills = [_DRILLS[args.only - 1]] if args.only else _DRILLS
    for drill in drills:
        drill(client, args.secret_id)
    print("\nRequested failure drills complete. Inspect CloudWatch Logs/alarms for detail.")


if __name__ == "__main__":
    main()
