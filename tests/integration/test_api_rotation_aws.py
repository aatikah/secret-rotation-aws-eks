"""AWS integration test: API credential rotation against real Secrets Manager.

Exercises the API-credential rotation workflow using the deployed
external-api secret in real Secrets Manager. The external provider is a mock
(no real third-party credentials are needed), but the AWS staging-label flow —
put AWSPENDING, validate, promote to AWSCURRENT — runs against the real service.

Requires RUN_AWS_INTEGRATION=1 and AWS credentials. Marked ``integration`` and
skipped by default. No secret values are printed.
"""

from __future__ import annotations

import uuid

import pytest

from secrets_rotation.rotation import api_credentials as api
from secrets_rotation.rotation import secretsmanager as sm

pytestmark = pytest.mark.integration


class MockApiProvider:
    """Mock external API with an overlapping-credentials contract."""

    supports_overlap = True

    def __init__(self, seed_key: str) -> None:
        self.active_keys = {seed_key}

    def rotate_key(self, current_key):
        new_key = f"key-{uuid.uuid4().hex[:12]}"
        self.active_keys.add(new_key)
        return new_key

    def validate_key(self, key):
        return key in self.active_keys

    def revoke_key(self, key):
        self.active_keys.discard(key)


def test_api_rotation_promotes_and_retires_old(sm_client, api_secret_id):
    # Ensure the secret has a current value to rotate from.
    try:
        current = sm.get_secret_dict(sm_client, api_secret_id, sm.AWSCURRENT)
    except sm_client.exceptions.ResourceNotFoundException:
        pytest.skip(f"{api_secret_id} not found; run scripts/create_dummy_secret.py first")

    seed = current.get("api_key")
    if not seed or seed == "PLACEHOLDER_SET_OUT_OF_BAND":
        pytest.skip("API secret still holds the placeholder; seed it with create_dummy_secret.py")

    provider = MockApiProvider(seed_key=seed)
    # rotate_api_credential owns its own AWSPENDING staging (step 3 calls
    # sm.put_pending_secret with this token), so the test must NOT pre-stage a
    # version with the same ClientRequestToken — doing so would collide and
    # Secrets Manager would reject the reused token. Just hand it a fresh token.
    token = uuid.uuid4().hex

    result = api.rotate_api_credential(sm_client, api_secret_id, token, provider)

    assert result.status == "succeeded"
    after = sm.get_secret_dict(sm_client, api_secret_id, sm.AWSCURRENT)
    assert after["api_key"] != seed
    assert provider.validate_key(after["api_key"]) is True
    # Old key retired only after a successful, validated transition.
    assert provider.validate_key(seed) is False
