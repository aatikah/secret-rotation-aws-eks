"""Audit reporting over CloudTrail and CloudWatch evidence.

Two event categories matter and they are NOT the same:

* **Management events** (CloudTrail, on by default): control-plane calls such as
  ``RotateSecret``, ``UpdateSecretVersionStage``, ``PutSecretValue``,
  ``DescribeSecret``. These tell you *that rotation happened* and *who changed
  configuration*.

* **Data events** / value retrieval (``GetSecretValue``): the actual reads of
  secret *material*. In CloudTrail these are recorded, but to reliably capture
  high-volume read patterns you must ensure the relevant trail/event selectors
  are enabled — you cannot assume every sensitive access is captured by the
  default management-event trail configuration.

This module parses CloudTrail-shaped event records (as returned by
``lookup_events`` or read from delivered log files) and summarises rotation and
access activity. It never emits secret values — only names, version IDs, event
names, identities, and timestamps.
"""

from __future__ import annotations

import datetime as _dt
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

_ROTATION_EVENTS = {"RotateSecret", "UpdateSecretVersionStage", "PutSecretValue"}
_READ_EVENTS = {"GetSecretValue"}


@dataclass
class AccessEvent:
    """A single normalised audit event (no secret material)."""

    event_time: _dt.datetime
    event_name: str
    secret_id: str | None
    principal: str | None
    source_ip: str | None
    version_id: str | None = None
    error_code: str | None = None


@dataclass
class AuditSummary:
    rotation_events: int = 0
    read_events: int = 0
    errors: int = 0
    by_principal: Counter[str] = field(default_factory=Counter)
    by_event: Counter[str] = field(default_factory=Counter)
    events: list[AccessEvent] = field(default_factory=list)


def _extract_secret_id(request_params: dict[str, Any] | None) -> str | None:
    if not request_params:
        return None
    return request_params.get("secretId") or request_params.get("SecretId")


def parse_cloudtrail_event(record: dict[str, Any]) -> AccessEvent:
    """Normalise a single CloudTrail event record into an :class:`AccessEvent`."""
    ts = record.get("eventTime") or record.get("EventTime")
    if isinstance(ts, str):
        # CloudTrail uses ISO 8601 with a trailing Z.
        event_time = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    elif isinstance(ts, _dt.datetime):
        event_time = ts
    else:
        event_time = _dt.datetime.now(_dt.UTC)

    user_identity = record.get("userIdentity", {}) or {}
    principal = (
        user_identity.get("arn")
        or user_identity.get("userName")
        or user_identity.get("type")
    )
    request_params = record.get("requestParameters") or {}
    response_elements = record.get("responseElements") or {}

    return AccessEvent(
        event_time=event_time,
        event_name=record.get("eventName", "Unknown"),
        secret_id=_extract_secret_id(request_params),
        principal=principal,
        source_ip=record.get("sourceIPAddress"),
        version_id=response_elements.get("versionId"),
        error_code=record.get("errorCode"),
    )


def summarise(records: list[dict[str, Any]]) -> AuditSummary:
    """Summarise a list of CloudTrail records into an :class:`AuditSummary`."""
    summary = AuditSummary()
    for record in records:
        event = parse_cloudtrail_event(record)
        summary.events.append(event)
        summary.by_event[event.event_name] += 1
        if event.principal:
            summary.by_principal[event.principal] += 1
        if event.error_code:
            summary.errors += 1
        if event.event_name in _ROTATION_EVENTS:
            summary.rotation_events += 1
        if event.event_name in _READ_EVENTS:
            summary.read_events += 1
    return summary


# ---- Example CloudWatch Logs Insights queries (returned as strings so the CLI
#      can print them for the operator to paste into the console / CLI). ----

CW_QUERY_FAILED_ROTATIONS = (
    "fields @timestamp, rotation_step, secret_name, version_id, message\n"
    "| filter level = 'ERROR' and ispresent(rotation_step)\n"
    "| sort @timestamp desc\n"
    "| limit 50"
)

CW_QUERY_ROTATION_DURATION = (
    "fields @timestamp, secret_name, rotation_step\n"
    "| filter ispresent(rotation_step)\n"
    "| stats earliest(@timestamp) as started, latest(@timestamp) as finished "
    "by secret_name, version_id"
)

CT_QUERY_UNUSUAL_ACCESS = (
    "CloudTrail Lake / Athena example:\n"
    "SELECT eventtime, eventname, useridentity.arn, sourceipaddress, errorcode\n"
    "FROM cloudtrail_logs\n"
    "WHERE eventsource = 'secretsmanager.amazonaws.com'\n"
    "  AND (errorcode IS NOT NULL OR eventname = 'GetSecretValue')\n"
    "ORDER BY eventtime DESC\n"
    "LIMIT 100;"
)
