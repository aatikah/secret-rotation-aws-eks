"""Unit tests proving secrets are redacted from logs."""

from __future__ import annotations

import json
import logging

from secrets_rotation import logging_config as lc


def _capture(logger: logging.Logger) -> list[str]:
    out: list[str] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            out.append(self.format(record))

    handler = _ListHandler()
    handler.setFormatter(lc.JsonFormatter())
    handler.addFilter(lc.RedactionFilter())
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return out


def test_password_in_connection_string_is_redacted():
    logger = logging.getLogger("test.redact.dsn")
    out = _capture(logger)
    logger.info("connecting to postgresql://app:SuperSecret123@db.local:5432/appdb")
    payload = json.loads(out[-1])
    assert "SuperSecret123" not in payload["message"]
    assert "REDACTED" in payload["message"]


def test_keyword_password_is_redacted():
    logger = logging.getLogger("test.redact.kw")
    out = _capture(logger)
    logger.info("auth failed with password=hunter2 for user app")
    payload = json.loads(out[-1])
    assert "hunter2" not in payload["message"]


def test_sensitive_context_field_is_masked():
    logger = logging.getLogger("test.redact.ctx")
    out = _capture(logger)
    logger.info(
        "rotation detail",
        extra={"context": {"secret_name": "dev/myapp/database", "password": "leaky"}},
    )
    payload = json.loads(out[-1])
    # Non-secret field preserved for auditing.
    assert payload["secret_name"] == "dev/myapp/database"
    # Secret field masked.
    assert payload["password"] == "***REDACTED***"


def test_private_key_block_is_redacted():
    logger = logging.getLogger("test.redact.pem")
    out = _capture(logger)
    pem = (
        "-----BEGIN PRIVATE KEY-----\nMIIBVAIBADAN...fakekeymaterial...\n"
        "-----END PRIVATE KEY-----"
    )
    logger.info("loaded key %s", pem)
    payload = json.loads(out[-1])
    assert "fakekeymaterial" not in payload["message"]
