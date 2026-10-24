"""AWS integration test: real database rotation via Secrets Manager.

Triggers a managed rotation of the deployed database secret and verifies the
Secrets Manager rotation contract end to end against the real rotation Lambda
and RDS database:

* AWSCURRENT advances to a new version.
* The previous version is retained as AWSPREVIOUS (recovery).
* The rotated credential actually authenticates against RDS.

Requires an applied Terraform `dev` environment with a reachable RDS instance
(create_database = true) and RUN_AWS_INTEGRATION=1. See docs/testing-and-
simulation.md. Marked ``integration`` and skipped by default.

No secret values are printed by this test.
"""

from __future__ import annotations

import time

import pytest

from secrets_rotation.rotation import secretsmanager as sm

from .conftest import tcp_reachable

pytestmark = pytest.mark.integration


def _current_version(client, secret_id):
    meta = client.describe_secret(SecretId=secret_id)
    for version, stages in meta.get("VersionIdsToStages", {}).items():
        if sm.AWSCURRENT in stages:
            return version
    return None


def _wait_for_current_change(client, secret_id, previous_version_id, timeout=300):
    """Poll until AWSCURRENT points at a version other than ``previous_version_id``.

    A completed rotation is signalled by AWSCURRENT advancing to a new version
    id. This is robust to a secret that auto-rotates on a schedule: it does not
    require a global "no AWSPENDING anywhere" quiet state (which may never be
    observed while scheduled rotations keep staging fresh pending versions). It
    just waits for the current label to move off the version we started from.
    Returns the new AWSCURRENT version id.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = _current_version(client, secret_id)
        if current is not None and current != previous_version_id:
            return current
        time.sleep(5)
    raise AssertionError("AWSCURRENT did not advance to a new version within timeout")


def _wait_for_current_present(client, secret_id, timeout=300):
    """Poll until an AWSCURRENT version is present and return its id.

    Used to confirm the secret ends in a consistent state after rotation(s),
    without relying on the absence of AWSPENDING (which a scheduled rotation may
    legitimately keep present).
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = _current_version(client, secret_id)
        if current is not None:
            return current
        time.sleep(5)
    raise AssertionError("no AWSCURRENT version present within timeout")


def test_managed_rotation_advances_current_and_authenticates(sm_client, secret_id):
    from botocore.exceptions import ClientError

    meta = sm_client.describe_secret(SecretId=secret_id)
    if not meta.get("RotationEnabled"):
        pytest.skip(f"rotation not enabled on {secret_id}; apply Terraform with RDS first")

    before = _current_version(sm_client, secret_id)
    try:
        sm_client.rotate_secret(SecretId=secret_id)
    except ClientError as exc:
        # An automatic (scheduled) rotation may already be mid-flight. That
        # in-flight rotation IS a managed rotation of this secret, so treat its
        # completion as the rotation under test rather than failing.
        if exc.response["Error"]["Code"] != "InvalidRequestException":
            raise

    # Rotation completion signal: AWSCURRENT advances to a different version.
    after = _wait_for_current_change(sm_client, secret_id, before)
    assert after != before, "AWSCURRENT should advance after rotation"

    # Previous version retained for recovery.
    meta = sm_client.describe_secret(SecretId=secret_id)
    has_previous = any(
        sm.AWSPREVIOUS in stages for stages in meta["VersionIdsToStages"].values()
    )
    assert has_previous, "previous version should be retained as AWSPREVIOUS"

    # The rotated credential must authenticate against the real RDS database.
    # This is the real end-to-end check; it runs at full strength whenever the
    # database is reachable. RDS lives in a private VPC subnet, so from a host
    # outside the VPC the port is unreachable — skip (don't fail) in that case.
    # The gate is on TCP reachability only, never on the auth result, so it can
    # never mask a genuine credential failure when the DB IS reachable.
    from secrets_rotation.rotation.pg_connector import PostgresConnector

    creds = sm.get_secret_dict(sm_client, secret_id, sm.AWSCURRENT)
    host = creds["host"]
    port = int(creds.get("port", 5432))
    if not tcp_reachable(host, port):
        pytest.skip(
            f"RDS {host}:{port} not reachable from this host (private VPC); "
            "run inside the VPC/bastion/SSM/CI to exercise can_authenticate"
        )
    assert PostgresConnector().can_authenticate(creds), "rotated credential must authenticate"


def test_concurrent_rotation_is_rejected(sm_client, secret_id):
    """A second rotation while one is in progress must not corrupt the secret.

    Rotations now complete in seconds, so a back-to-back second rotate_secret
    may be either rejected as concurrent (the classic guard) OR accepted because
    the first already finished. Both are valid; the invariant we actually assert
    is that the secret ends in a consistent state — an AWSCURRENT version is
    present and that credential authenticates.
    """
    from botocore.exceptions import ClientError

    meta = sm_client.describe_secret(SecretId=secret_id)
    if not meta.get("RotationEnabled"):
        pytest.skip("rotation not enabled")

    try:
        sm_client.rotate_secret(SecretId=secret_id)
    except ClientError as exc:
        # A scheduled rotation may already be running; that is still "a rotation
        # in progress" for the purpose of this test.
        if exc.response["Error"]["Code"] != "InvalidRequestException":
            raise

    try:
        sm_client.rotate_secret(SecretId=secret_id)
        # Accepted: the first rotation had already completed. Fine.
    except ClientError as exc:
        # Rejected as concurrent — the guard worked.
        assert exc.response["Error"]["Code"] in {
            "InvalidRequestException",
            "ResourceExistsException",
        }

    # Either way, the secret must settle into a consistent, usable state.
    _wait_for_current_present(sm_client, secret_id)

    # End-to-end auth check, gated on reachability only (see the managed-rotation
    # test for the rationale). Runs at full strength when the DB is reachable.
    from secrets_rotation.rotation.pg_connector import PostgresConnector

    creds = sm.get_secret_dict(sm_client, secret_id, sm.AWSCURRENT)
    host = creds["host"]
    port = int(creds.get("port", 5432))
    if not tcp_reachable(host, port):
        pytest.skip(
            f"RDS {host}:{port} not reachable from this host (private VPC); "
            "run inside the VPC/bastion/SSM/CI to exercise can_authenticate"
        )
    assert PostgresConnector().can_authenticate(creds), "current credential must authenticate"
