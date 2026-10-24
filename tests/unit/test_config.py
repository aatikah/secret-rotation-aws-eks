"""Unit tests for config and the secret naming convention."""

from __future__ import annotations

import pytest

from secrets_rotation import config


def test_secret_name_convention():
    assert config.secret_name("dev", "myapp", "database") == "dev/myapp/database"
    assert config.secret_name("prod", "billing", "tls") == "prod/billing/tls"


def test_secret_name_rejects_bad_env():
    with pytest.raises(ValueError):
        config.secret_name("staging", "myapp", "database")


def test_secret_name_rejects_bad_kind():
    with pytest.raises(ValueError):
        config.secret_name("dev", "myapp", "cert")


def test_secret_name_rejects_slash_in_app():
    with pytest.raises(ValueError):
        config.secret_name("dev", "my/app", "database")


def test_parse_secret_name_roundtrip():
    assert config.parse_secret_name("dev/myapp/external-api") == ("dev", "myapp", "external-api")


def test_parse_secret_name_rejects_malformed():
    with pytest.raises(ValueError):
        config.parse_secret_name("dev/myapp")
