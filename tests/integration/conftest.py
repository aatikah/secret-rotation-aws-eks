"""Fixtures for AWS integration tests.

These tests run against a REAL, deployed AWS environment (Secrets Manager +
rotation Lambda + RDS created by Terraform). They are marked ``integration`` and
skipped by default. Enable them by setting ``RUN_AWS_INTEGRATION=1`` and valid
AWS credentials.

Target configuration via environment:
    AWS_REGION           (default us-east-1)
    SECRET_ID            (default dev/myapp/database) — the deployed DB secret
    API_SECRET_ID        (default dev/myapp/external-api)
"""

from __future__ import annotations

import os
import socket

import pytest


def _integration_enabled() -> bool:
    return os.environ.get("RUN_AWS_INTEGRATION") == "1"


def tcp_reachable(host: str, port: int, timeout: float = 4.0) -> bool:
    """Return True if a TCP connection to ``host:port`` can be opened quickly.

    Used by the database integration tests to gate the end-to-end
    ``can_authenticate`` check: the RDS instance lives in a private VPC subnet
    and is unreachable from a developer workstation outside the VPC. The gate is
    purely about reachability — it never inspects auth results — so it can never
    mask a genuine credential failure when the database IS reachable (CI inside
    the VPC, a bastion, or an SSM port-forward).
    """
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def aws_region() -> str:
    return os.environ.get("AWS_REGION", "us-east-1")


@pytest.fixture(scope="session")
def secret_id() -> str:
    return os.environ.get("SECRET_ID", "dev/myapp/database")


@pytest.fixture(scope="session")
def api_secret_id() -> str:
    return os.environ.get("API_SECRET_ID", "dev/myapp/external-api")


@pytest.fixture(scope="session")
def sm_client(aws_region: str):
    if not _integration_enabled():
        pytest.skip("set RUN_AWS_INTEGRATION=1 (and AWS credentials) to run AWS integration tests")
    boto3 = pytest.importorskip("boto3")
    from botocore.exceptions import NoCredentialsError

    client = boto3.client("secretsmanager", region_name=aws_region)
    try:
        client.list_secrets(MaxResults=1)
    except NoCredentialsError:
        pytest.skip("no AWS credentials available")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"cannot reach AWS Secrets Manager: {exc}")
    return client
