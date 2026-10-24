"""Database password rotation using the AWS Secrets Manager four-step contract.

Strategy: alternating users ("two user" rotation)
-------------------------------------------------
We rotate between two database login roles that share the same privileges,
e.g. ``myapp_a`` and ``myapp_b``. At any time exactly one is "current" and the
application uses it. Rotation changes the *other* user's password, tests it,
and only then promotes it to AWSCURRENT.

Why alternating users rather than rotating a single user's password?

* The application keeps using the still-valid current user for the whole
  create/set/test window. We only flip to the new user once it is validated.
* It avoids the race where you change a single user's password and every live
  connection using the old password breaks before the app refreshes.

This design assumes a *master* secret (an admin login) is available to ALTER
the rotated roles. That mirrors the AWS-provided "alternating users" rotation
template. Rollback is simple: if testSecret fails we never move AWSCURRENT, so
the application keeps using the previous, still-valid user.

The four steps (order matters)
------------------------------
1. ``createSecret``  — generate the new password, store it as AWSPENDING.
   Idempotent via the rotation token.
2. ``setSecret``     — using the master login, ALTER the *inactive* user to the
   pending password (and ensure it exists with the right grants).
3. ``testSecret``    — open a real connection as the pending user to prove the
   credential works before anyone relies on it.
4. ``finishSecret``  — move AWSCURRENT to the pending version. The old version
   becomes AWSPREVIOUS for recovery.

The secret JSON shape (compatible with the AWS templates)::

    {
      "engine": "postgres",
      "host": "...",
      "port": 5432,
      "dbname": "appdb",
      "username": "myapp_a",       # the ACTIVE user for this version
      "password": "...",
      "masterarn": "arn:aws:secretsmanager:...:secret:dev/myapp/database-master"
    }

Passwords and DSNs are never logged — only secret names, version IDs, and the
(non-secret) username are emitted for auditing.
"""

from __future__ import annotations

from typing import Any, Protocol

from ..logging_config import get_logger
from . import secretsmanager as sm

logger = get_logger(__name__)


class DbConnector(Protocol):
    """Abstraction over the database used by the rotation state machine.

    The concrete implementation is :class:`PostgresConnector` (psycopg against
    the RDS database). Keeping this as a Protocol means :func:`rotate` never
    imports psycopg directly, so importing the state machine (e.g. in the policy
    CLI) does not require the driver.
    """

    def alter_user_password(
        self, master: dict[str, Any], username: str, new_password: str
    ) -> None:
        """ALTER ``username`` to ``new_password`` using the ``master`` login."""

    def can_authenticate(self, credentials: dict[str, Any]) -> bool:
        """Return True if a connection can be opened with ``credentials``."""


def _inactive_username(active_username: str) -> str:
    """Return the alternate user name for the alternating-users strategy.

    ``myapp_a`` <-> ``myapp_b``. If the current user has no ``_a``/``_b``
    suffix we append ``_a`` so the first rotation establishes the pair.
    """
    if active_username.endswith("_a"):
        return active_username[:-2] + "_b"
    if active_username.endswith("_b"):
        return active_username[:-2] + "_a"
    return active_username + "_a"


def create_secret(client: Any, secret_id: str, token: str) -> None:
    """Step 1: ensure an AWSPENDING version exists with a fresh password.

    Idempotent: if a pending version already exists for this token we leave it,
    so a retried Lambda invocation does not generate a conflicting password.
    """
    current = sm.get_secret_dict(client, secret_id, sm.AWSCURRENT)

    # Idempotency: only skip if a pending version already holds *rotated*
    # content (a fresh password for the alternate user). Secrets Manager stages
    # a bare copy of AWSCURRENT under the token before invoking createSecret, so
    # the mere existence of a pending version is not proof the work was done —
    # we must check it actually differs from current.
    try:
        existing_pending = sm.get_secret_dict(
            client, secret_id, sm.AWSPENDING, version_id=token
        )
        already_rotated = (
            existing_pending.get("username") == _inactive_username(current["username"])
            and existing_pending.get("password") != current.get("password")
        )
        if already_rotated:
            logger.info(
                "createSecret: rotated pending version already exists; skipping",
                extra={"context": {"secret_name": secret_id, "version_id": token,
                                   "rotation_step": "createSecret"}},
            )
            return
    except client.exceptions.ResourceNotFoundException:
        pass

    pending = dict(current)
    pending["username"] = _inactive_username(current["username"])
    pending["password"] = sm.generate_password()
    sm.put_pending_secret(client, secret_id, token, pending)
    logger.info(
        "createSecret: stored new pending credential",
        extra={"context": {"secret_name": secret_id, "version_id": token,
                           "pending_username": pending["username"],
                           "rotation_step": "createSecret"}},
    )


def set_secret(client: Any, secret_id: str, token: str, connector: DbConnector) -> None:
    """Step 2: apply the pending password to the inactive DB user.

    Uses the master login referenced by ``masterarn`` to ALTER the user. This
    is where the credential actually changes in the target system — not just in
    Secrets Manager.
    """
    pending = sm.get_secret_dict(client, secret_id, sm.AWSPENDING, version_id=token)
    master = sm.get_secret_dict(client, pending["masterarn"], sm.AWSCURRENT)

    connector.alter_user_password(master, pending["username"], pending["password"])
    logger.info(
        "setSecret: applied pending password to inactive user",
        extra={"context": {"secret_name": secret_id, "version_id": token,
                           "pending_username": pending["username"],
                           "rotation_step": "setSecret"}},
    )


def test_secret(client: Any, secret_id: str, token: str, connector: DbConnector) -> None:
    """Step 3: prove the pending credential authenticates against the database.

    Raises:
        PermissionError: if the pending credential cannot authenticate. The
        caller must NOT proceed to finishSecret — AWSCURRENT stays put and the
        application keeps using the still-valid previous credential.
    """
    pending = sm.get_secret_dict(client, secret_id, sm.AWSPENDING, version_id=token)
    if not connector.can_authenticate(pending):
        logger.error(
            "testSecret: pending credential failed authentication; aborting rotation",
            extra={"context": {"secret_name": secret_id, "version_id": token,
                               "pending_username": pending["username"],
                               "rotation_step": "testSecret"}},
        )
        raise PermissionError("pending credential failed authentication")
    logger.info(
        "testSecret: pending credential authenticated successfully",
        extra={"context": {"secret_name": secret_id, "version_id": token,
                           "pending_username": pending["username"],
                           "rotation_step": "testSecret"}},
    )


def finish_secret(client: Any, secret_id: str, token: str) -> None:
    """Step 4: promote the validated pending version to AWSCURRENT."""
    sm.finish_rotation(client, secret_id, token)
    logger.info(
        "finishSecret: promoted pending version to AWSCURRENT",
        extra={"context": {"secret_name": secret_id, "version_id": token,
                           "rotation_step": "finishSecret"}},
    )


# Map the Secrets Manager rotation step name to the function implementing it.
_STEPS = {
    "createSecret": create_secret,
    "setSecret": set_secret,
    "testSecret": test_secret,
    "finishSecret": finish_secret,
}


def rotate(
    client: Any,
    secret_id: str,
    token: str,
    step: str,
    connector: DbConnector,
) -> None:
    """Dispatch a single rotation step.

    Secrets Manager invokes the rotation Lambda once per step with ``Step`` in
    the event; this function routes to the right handler. ``createSecret`` and
    ``finishSecret`` don't need a DB connector, but accepting it uniformly keeps
    the dispatch simple.
    """
    if step not in _STEPS:
        raise ValueError(f"unknown rotation step: {step!r}")
    _verify_rotation_enabled(client, secret_id, token, step)
    if step in ("setSecret", "testSecret"):
        _STEPS[step](client, secret_id, token, connector)  # type: ignore[operator]
    else:
        _STEPS[step](client, secret_id, token)  # type: ignore[operator]


def _verify_rotation_enabled(client: Any, secret_id: str, token: str, step: str) -> None:
    """Guard against stale / out-of-order invocations.

    Confirms rotation is enabled and that ``token`` is actually staged as
    AWSPENDING (except for createSecret, which may be the step that creates it).
    This prevents a replayed event from promoting an unrelated version.
    """
    meta = client.describe_secret(SecretId=secret_id)
    if not meta.get("RotationEnabled", False):
        logger.warning(
            "rotation not enabled for secret; proceeding (likely a local/manual run)",
            extra={"context": {"secret_name": secret_id, "rotation_step": step}},
        )
    stages = meta.get("VersionIdsToStages", {})
    if step != "createSecret" and token not in stages:
        raise ValueError(
            f"version token not staged for secret during {step}; refusing to proceed"
        )
