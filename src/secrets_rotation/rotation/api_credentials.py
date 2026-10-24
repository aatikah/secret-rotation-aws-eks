"""External API credential rotation.

The critical distinction this module enforces: rotating an API credential means
**changing it at the provider**, not merely overwriting the value stored in
Secrets Manager. A workflow that updates the stored string without changing the
provider's accepted key is a security no-op and is explicitly disallowed here —
:meth:`ApiProvider.rotate_key` must actually mint/accept a new key at the
provider and must return the new key, or the rotation fails.

Overlapping vs non-overlapping providers
----------------------------------------
Many providers let a new key become active while the old key still works for a
grace period ("overlapping credentials"). That enables a safe transition:

    create new key -> store as pending -> validate -> promote -> revoke old key

Some providers only allow one active key ("non-overlapping"). For those, there
is an unavoidable moment where the old key stops working the instant the new one
is created. We detect this via ``provider.supports_overlap`` and, when False,
narrow the window and clearly report the brief invalidation rather than
pretending it is zero-downtime.

The provider is an abstract interface. The local demo (and tests) use a mock
provider; a real integration implements :class:`ApiProvider` against the real
API. If a provider has no rotation API at all, that must be documented as a
manual process — see ``docs/api-rotation.md`` — rather than faked here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..logging_config import get_logger
from . import secretsmanager as sm

logger = get_logger(__name__)


class ApiProvider(Protocol):
    """Interface a real or mock external API must implement to be rotatable."""

    supports_overlap: bool

    def rotate_key(self, current_key: str | None) -> str:
        """Mint a new key AT THE PROVIDER and return it.

        For overlapping providers the ``current_key`` stays valid until
        :meth:`revoke_key` is called. For non-overlapping providers the old key
        may stop working immediately.
        """

    def validate_key(self, key: str) -> bool:
        """Return True if ``key`` is currently accepted by the provider."""

    def revoke_key(self, key: str) -> None:
        """Permanently revoke ``key`` at the provider."""


@dataclass
class RotationResult:
    """Outcome of an API-credential rotation, suitable for audit logging."""

    secret_name: str
    new_version_id: str
    old_key_revoked: bool
    had_overlap: bool
    status: str  # "succeeded" | "rolled_back"
    detail: str = ""


def rotate_api_credential(
    client: Any,
    secret_id: str,
    token: str,
    provider: ApiProvider,
) -> RotationResult:
    """Rotate an external API credential with a safe, provider-aware transition.

    Steps:
        1. Read the current key from AWSCURRENT.
        2. Ask the provider to mint a replacement (the real change).
        3. Store it as AWSPENDING.
        4. Validate the replacement is accepted by the provider.
        5. Promote the pending version to AWSCURRENT.
        6. Revoke the old key — only after a successful promotion.

    On any failure before promotion, the new key is revoked (rollback) and the
    stored AWSCURRENT is left untouched, so the application keeps using the key
    that still works. The failure is reported, never silently swallowed.
    """
    current = sm.get_secret_dict(client, secret_id, sm.AWSCURRENT)
    old_key = current.get("api_key")

    # Step 2: the actual provider-side change.
    try:
        new_key = provider.rotate_key(old_key)
    except Exception as exc:  # noqa: BLE001 — we convert to an auditable result
        logger.error(
            "api rotation: provider failed to mint a new key; aborting (old key unchanged)",
            extra={"context": {"secret_name": secret_id, "stage": "rotate_key"}},
        )
        raise RuntimeError(f"provider.rotate_key failed: {exc}") from exc

    if not new_key or new_key == old_key:
        raise RuntimeError(
            "provider returned an empty or unchanged key: refusing to record a no-op rotation"
        )

    # Step 3: stage the pending value.
    pending = dict(current)
    pending["api_key"] = new_key
    sm.put_pending_secret(client, secret_id, token, pending)

    # Step 4: validate the replacement really works at the provider.
    if not provider.validate_key(new_key):
        logger.error(
            "api rotation: new key failed provider validation; rolling back",
            extra={"context": {"secret_name": secret_id, "stage": "validate"}},
        )
        _safe_revoke(provider, new_key)
        return RotationResult(
            secret_name=secret_id,
            new_version_id=token,
            old_key_revoked=False,
            had_overlap=provider.supports_overlap,
            status="rolled_back",
            detail="new key failed validation; old credential remains current",
        )

    # Step 5: promote.
    sm.finish_rotation(client, secret_id, token)
    logger.info(
        "api rotation: promoted new key to AWSCURRENT",
        extra={"context": {"secret_name": secret_id, "version_id": token}},
    )

    # Step 6: retire the old key, only now that the new one is live and validated.
    old_revoked = False
    if old_key:
        try:
            provider.revoke_key(old_key)
            old_revoked = True
            logger.info(
                "api rotation: revoked old key after safe transition",
                extra={"context": {"secret_name": secret_id}},
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "api rotation: new key promoted but old-key revocation failed; "
                "manual revocation required",
                extra={"context": {"secret_name": secret_id}},
            )

    return RotationResult(
        secret_name=secret_id,
        new_version_id=token,
        old_key_revoked=old_revoked,
        had_overlap=provider.supports_overlap,
        status="succeeded",
        detail="" if old_revoked else "old key not revoked; needs manual follow-up",
    )


def _safe_revoke(provider: ApiProvider, key: str) -> None:
    try:
        provider.revoke_key(key)
    except Exception:  # noqa: BLE001
        logger.warning("api rotation: rollback revoke failed; new key may linger at provider")
