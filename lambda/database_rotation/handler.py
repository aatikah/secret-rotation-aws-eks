"""AWS Lambda entry point for PostgreSQL password rotation.

Secrets Manager invokes this handler once per rotation step with an event::

    {
      "SecretId": "arn:aws:secretsmanager:...:secret:dev/myapp/database-xxxx",
      "ClientRequestToken": "<uuid>",     # the AWSPENDING version id
      "Step": "createSecret" | "setSecret" | "testSecret" | "finishSecret"
    }

The handler is intentionally thin: it validates the event, builds a boto3
client and a real :class:`PostgresConnector`, and delegates to the pure state
machine in :mod:`secrets_rotation.rotation.database`, which is unit-tested
offline. Keeping the logic in the library (not the handler) is what lets CI
test rotation without deploying a Lambda.

Packaging: this directory is zipped with the ``secrets_rotation`` package and
its dependencies (boto3 is in the Lambda runtime; psycopg[binary] is bundled).
See ``terraform/modules/rotation-lambda`` and ``requirements.txt``.
"""

from __future__ import annotations

import os
from typing import Any

import boto3

from secrets_rotation.logging_config import configure_logging
from secrets_rotation.rotation import database
from secrets_rotation.rotation.pg_connector import PostgresConnector

logger = configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"), name="rotation_lambda")

_VALID_STEPS = {"createSecret", "setSecret", "testSecret", "finishSecret"}


def lambda_handler(event: dict[str, Any], context: Any) -> None:
    """Rotation Lambda entry point.

    Raises on error so Secrets Manager marks the step failed and retries per the
    rotation configuration. We never promote on failure: ``finishSecret`` is a
    separate step that only runs after ``testSecret`` has succeeded.
    """
    secret_id = event["SecretId"]
    token = event["ClientRequestToken"]
    step = event["Step"]

    if step not in _VALID_STEPS:
        raise ValueError(f"invalid rotation step: {step!r}")

    logger.info(
        "rotation invoked",
        extra={"context": {"secret_name": secret_id, "version_id": token,
                           "rotation_step": step}},
    )

    client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION"))
    connector = PostgresConnector()

    try:
        database.rotate(client, secret_id, token, step, connector)
    except Exception:
        # The exception detail is logged by the state machine (already redacted).
        logger.exception(
            "rotation step failed",
            extra={"context": {"secret_name": secret_id, "version_id": token,
                               "rotation_step": step}},
        )
        raise

    logger.info(
        "rotation step completed",
        extra={"context": {"secret_name": secret_id, "version_id": token,
                           "rotation_step": step}},
    )
