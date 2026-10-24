"""Configuration and the secret naming convention.

Configuration is environment-driven so the same code runs locally, in Lambda,
and in CI without edits. No secret *values* are read from configuration here —
only pointers (names, regions, intervals). Actual secret material always comes
from AWS Secrets Manager at runtime.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Final

# Supported secret "kinds". The kind is the last path segment of a secret name
# and tells tooling how to interpret / rotate the secret.
SECRET_KINDS: Final[tuple[str, ...]] = ("database", "external-api", "tls", "application")

# Supported environments. Dev and prod are kept in separate namespaces with
# separate permissions; credentials are never shared between them.
ENVIRONMENTS: Final[tuple[str, ...]] = ("dev", "prod")


def _get(name: str, default: str) -> str:
    value = os.environ.get(name, default)
    return value if value != "" else default


@dataclass(frozen=True)
class Settings:
    """Resolved runtime settings.

    Attributes:
        aws_region: Region for all boto3 clients and Terraform.
        environment: Namespace prefix for secret names (``dev`` or ``prod``).
        app_name: Logical application name used in ``<env>/<app>/<kind>``.
        log_level: Structured-logger level.
        policy_file: Path to the YAML rotation policy.
    """

    aws_region: str = field(default_factory=lambda: _get("AWS_REGION", "us-east-1"))
    environment: str = field(default_factory=lambda: _get("SECRETS_ENV", "dev"))
    app_name: str = field(default_factory=lambda: _get("APP_NAME", "myapp"))
    log_level: str = field(default_factory=lambda: _get("LOG_LEVEL", "INFO"))
    policy_file: str = field(
        default_factory=lambda: _get("POLICY_FILE", "policies/rotation-policy.yaml")
    )

    def __post_init__(self) -> None:
        if self.environment not in ENVIRONMENTS:
            raise ValueError(
                f"SECRETS_ENV must be one of {ENVIRONMENTS}, got {self.environment!r}"
            )


def secret_name(environment: str, app: str, kind: str) -> str:
    """Build a secret name following the ``<env>/<app>/<kind>`` convention.

    Example:
        >>> secret_name("dev", "myapp", "database")
        'dev/myapp/database'
    """
    if environment not in ENVIRONMENTS:
        raise ValueError(f"environment must be one of {ENVIRONMENTS}, got {environment!r}")
    if kind not in SECRET_KINDS:
        raise ValueError(f"kind must be one of {SECRET_KINDS}, got {kind!r}")
    if not app or "/" in app:
        raise ValueError(f"app must be non-empty and contain no '/', got {app!r}")
    return f"{environment}/{app}/{kind}"


def parse_secret_name(name: str) -> tuple[str, str, str]:
    """Split a secret name into ``(environment, app, kind)``.

    Raises:
        ValueError: if the name does not follow the convention.
    """
    parts = name.split("/")
    if len(parts) != 3:
        raise ValueError(f"secret name must be '<env>/<app>/<kind>', got {name!r}")
    environment, app, kind = parts
    if environment not in ENVIRONMENTS or kind not in SECRET_KINDS or not app:
        raise ValueError(f"secret name does not follow the convention: {name!r}")
    return environment, app, kind
