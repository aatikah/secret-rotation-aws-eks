"""Secrets rotation platform.

A modular, locally testable implementation of an enterprise secrets
management and rotation workflow built around AWS Secrets Manager.

Submodules:
    config          Environment-driven configuration and the secret naming convention.
    logging_config  Structured JSON logging with secret redaction.
    rotation        Database, API-credential, and certificate rotation logic.
    policy          Rotation-policy compliance checking.
    audit           Reporting over CloudTrail / CloudWatch evidence.
    cli             Command-line entry point.
"""

__version__ = "0.1.0"
