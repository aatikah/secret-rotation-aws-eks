"""Structured JSON logging with secret redaction.

Two concerns are handled here:

1. **Structured output.** Logs are emitted as single-line JSON so CloudWatch
   Logs Insights (and local tooling) can query fields like ``rotation_step``,
   ``secret_name``, and ``version_id`` without brittle regex parsing.

2. **Redaction.** A logging filter scrubs values that look like secret
   material (passwords, tokens, authorization headers, private keys,
   connection strings) *before* a record is formatted. Redaction is defense in
   depth: the rotation code is written never to log secrets in the first
   place, but a stray ``f"{conn_string}"`` must never leak a password into
   CloudWatch.

The redactor never sees the secret *name* as sensitive — names and version IDs
are safe to log and are what we want for auditing.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

# Keys whose values must always be masked, regardless of content.
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "secret_value",
        "secretstring",
        "token",
        "api_key",
        "apikey",
        "access_key",
        "secret_access_key",
        "authorization",
        "auth",
        "private_key",
        "privatekey",
        "connection_string",
        "conn_string",
        "dsn",
    }
)

_MASK = "***REDACTED***"

# Patterns that catch secret material embedded in free-form message strings.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    # postgresql://user:password@host  ->  mask the password component
    re.compile(r"(?P<scheme>[a-zA-Z0-9+.\-]+://[^:/\s]+:)(?P<pw>[^@/\s]+)(?P<rest>@)"),
    # password=... / pwd:... / token = ...
    re.compile(
        r"(?i)(?P<key>password|passwd|pwd|token|api[_-]?key|secret|authorization)"
        r"(?P<sep>\s*[=:]\s*)(?P<val>[^\s,;}\"']+)"
    ),
    # PEM private key blocks
    re.compile(
        r"-----BEGIN (?:RSA |EC |)PRIVATE KEY-----.*?-----END (?:RSA |EC |)PRIVATE KEY-----",
        re.DOTALL,
    ),
)


def redact_text(text: str) -> str:
    """Mask secret-looking substrings in a free-form string."""
    out = text
    out = _PATTERNS[0].sub(rf"\g<scheme>{_MASK}\g<rest>", out)
    out = _PATTERNS[1].sub(rf"\g<key>\g<sep>{_MASK}", out)
    out = _PATTERNS[2].sub(_MASK, out)
    return out


def redact_value(key: str, value: Any) -> Any:
    """Mask ``value`` when ``key`` is sensitive; recurse into dict/list."""
    if isinstance(value, dict):
        return {k: redact_value(k, v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(key, v) for v in value]
    if key.lower() in _SENSITIVE_KEYS:
        return _MASK
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactionFilter(logging.Filter):
    """Logging filter that scrubs the message and structured ``extra`` fields."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: redact_value(k, v) for k, v in record.args.items()}
            else:
                record.args = tuple(redact_value("", a) for a in record.args)
        # Structured fields attached via logger.info(..., extra={"context": {...}})
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            record.context = {k: redact_value(k, v) for k, v in context.items()}
        return True


class JsonFormatter(logging.Formatter):
    """Format a record as a single-line JSON object."""

    _RESERVED = frozenset(logging.makeLogRecord({}).__dict__.keys()) | {
        "message",
        "asctime",
        "context",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload.update(context)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(level: str = "INFO", name: str = "secrets_rotation") -> logging.Logger:
    """Configure and return the package logger.

    Idempotent: repeated calls do not add duplicate handlers.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level.upper())
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler.addFilter(RedactionFilter())
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(name: str = "secrets_rotation") -> logging.Logger:
    """Return the package logger, configuring it with defaults if needed."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        return configure_logging(name=name)
    return logger
