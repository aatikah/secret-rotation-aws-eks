"""Thin, typed helpers over the Secrets Manager rotation API.

These helpers centralise the staging-label semantics that make rotation safe:

* ``AWSCURRENT``  -> the version applications read right now.
* ``AWSPENDING``  -> the candidate version being created/tested during rotation.
* ``AWSPREVIOUS`` -> the version demoted from current, kept for recovery.

The functions are deliberately small and side-effect-explicit so the rotation
state machine in :mod:`secrets_rotation.rotation.database` reads clearly and so
the AWS integration tests can drive them against real Secrets Manager.
"""

from __future__ import annotations

import json
import secrets
import string
from typing import Any

# Minimum entropy for generated passwords. 32 chars from a 70-char alphabet is
# ~196 bits, comfortably above any practical brute-force threshold.
_PASSWORD_LENGTH = 32
# Exclude characters that commonly break shell/URL/SQL contexts to keep the
# generated password safe to transport, while staying high-entropy.
_PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!#%*-_=+:?"

AWSCURRENT = "AWSCURRENT"
AWSPENDING = "AWSPENDING"
AWSPREVIOUS = "AWSPREVIOUS"


def generate_password(length: int = _PASSWORD_LENGTH) -> str:
    """Generate a high-entropy password using the OS CSPRNG.

    Uses :func:`secrets.choice` (cryptographically secure), not :mod:`random`.
    Guarantees at least one lower, upper, digit, and symbol so it satisfies
    common database password-complexity rules.
    """
    if length < 16:
        raise ValueError("refusing to generate a password shorter than 16 characters")
    while True:
        pw = "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))
        if (
            any(c.islower() for c in pw)
            and any(c.isupper() for c in pw)
            and any(c.isdigit() for c in pw)
            and any(c in "!#%*-_=+:?" for c in pw)
        ):
            return pw


def get_secret_dict(
    client: Any, secret_id: str, stage: str, version_id: str | None = None
) -> dict[str, Any]:
    """Fetch a secret value for a staging label and parse it as JSON.

    Args:
        client: a boto3 ``secretsmanager`` client.
        secret_id: ARN or name of the secret.
        stage: staging label (e.g. ``AWSCURRENT``).
        version_id: optional explicit version; overrides ``stage`` when given.
    """
    kwargs: dict[str, Any] = {"SecretId": secret_id}
    if version_id is not None:
        kwargs["VersionId"] = version_id
    else:
        kwargs["VersionStage"] = stage
    resp = client.get_secret_value(**kwargs)
    return json.loads(resp["SecretString"])


def put_pending_secret(
    client: Any, secret_id: str, token: str, secret_dict: dict[str, Any]
) -> None:
    """Store ``secret_dict`` as the AWSPENDING version keyed to ``token``.

    ``ClientRequestToken`` is the rotation token Secrets Manager passes to the
    Lambda; reusing it makes ``createSecret`` idempotent — a retried invocation
    writes the same version rather than minting a new password.
    """
    client.put_secret_value(
        SecretId=secret_id,
        ClientRequestToken=token,
        SecretString=json.dumps(secret_dict),
        VersionStages=[AWSPENDING],
    )


def finish_rotation(client: Any, secret_id: str, token: str) -> None:
    """Promote the AWSPENDING version (``token``) to AWSCURRENT.

    Moving the ``AWSCURRENT`` label automatically demotes the old current
    version to ``AWSPREVIOUS`` (recovery copy) and clears ``AWSPENDING``.
    """
    meta = client.describe_secret(SecretId=secret_id)
    current_version = None
    for version, stages in meta.get("VersionIdsToStages", {}).items():
        if AWSCURRENT in stages:
            current_version = version
            break
    if current_version == token:
        # Already promoted — idempotent no-op on retry.
        return
    client.update_secret_version_stage(
        SecretId=secret_id,
        VersionStage=AWSCURRENT,
        MoveToVersionId=token,
        RemoveFromVersionId=current_version,
    )
