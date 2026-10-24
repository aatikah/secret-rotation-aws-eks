"""Pure-logic unit tests for rotation helpers (no AWS, no database).

These cover the deterministic parts of the rotation code that need no Secrets
Manager client: password generation and the alternating-users mapping. The
full rotation lifecycle (which calls Secrets Manager) is verified by the AWS
integration tests in tests/integration.
"""

from __future__ import annotations

import pytest

from secrets_rotation.rotation import database
from secrets_rotation.rotation import secretsmanager as sm


def test_generated_password_is_high_entropy_and_complex():
    pw = sm.generate_password()
    assert len(pw) >= 32
    assert any(c.islower() for c in pw)
    assert any(c.isupper() for c in pw)
    assert any(c.isdigit() for c in pw)
    assert sm.generate_password() != sm.generate_password()


def test_refuses_short_password():
    with pytest.raises(ValueError):
        sm.generate_password(length=8)


def test_alternating_username_mapping():
    assert database._inactive_username("myapp_a") == "myapp_b"
    assert database._inactive_username("myapp_b") == "myapp_a"
    # First rotation of a user with no suffix establishes the pair.
    assert database._inactive_username("myapp") == "myapp_a"


def test_rotate_rejects_unknown_step():
    with pytest.raises(ValueError):
        database.rotate(client=None, secret_id="x", token="t", step="bogus", connector=None)
