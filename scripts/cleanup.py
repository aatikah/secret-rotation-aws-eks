"""Delete the dummy secrets created for this project (live AWS).

By default secrets are scheduled for deletion with a recovery window (safer).
Pass ``--force`` to delete immediately with no recovery (irreversible).

IMPORTANT: scheduled-for-deletion secrets can still incur storage until the
window elapses, and immediately-deleted secrets cannot be recovered. Review the
list before confirming.

Usage (requires AWS credentials):
    python scripts/cleanup.py                 # schedule deletion (7-day window)
    python scripts/cleanup.py --force         # delete immediately (irreversible)
"""

from __future__ import annotations

import argparse

import boto3

_DEFAULT_SECRETS = [
    "dev/myapp/database",
    "dev/myapp/database-master",
    "dev/myapp/external-api",
    "dev/myapp/tls",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--force", action="store_true",
                        help="Delete immediately with no recovery window (irreversible).")
    parser.add_argument("--recovery-days", type=int, default=7)
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = parser.parse_args()

    client = boto3.client("secretsmanager", region_name=args.region)

    print("The following secrets will be deleted:")
    for name in _DEFAULT_SECRETS:
        print(f"  {name}")
    mode = "IMMEDIATELY (irreversible)" if args.force else f"with a {args.recovery_days}-day window"
    print(f"Deletion mode: {mode}")

    if not args.yes:
        confirm = input("Type 'delete' to proceed: ")
        if confirm != "delete":
            print("Aborted.")
            return

    for name in _DEFAULT_SECRETS:
        try:
            if args.force:
                client.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)
            else:
                client.delete_secret(SecretId=name, RecoveryWindowInDays=args.recovery_days)
            print(f"  deleted: {name}")
        except client.exceptions.ResourceNotFoundException:
            print(f"  not found (skipped): {name}")


if __name__ == "__main__":
    main()
