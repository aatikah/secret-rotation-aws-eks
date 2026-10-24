"""Unit tests for the rotation-policy compliance checker."""

from __future__ import annotations

import datetime as _dt

from secrets_rotation.policy import compliance as c

_UTC = _dt.UTC
_NOW = _dt.datetime(2026, 10, 12, tzinfo=_UTC)


def _policy() -> c.Policy:
    return c.Policy(
        max_rotation_interval_days=90,
        cert_expiry_warning_days=30,
        required_tags=("owner", "environment"),
        require_rotation_enabled=True,
    )


def test_compliant_secret_passes():
    desc = c.SecretDescriptor(
        name="dev/myapp/database",
        rotation_enabled=True,
        rotation_interval_days=30,
        last_rotated=_NOW - _dt.timedelta(days=5),
        tags={"owner": "team-a", "environment": "dev"},
        last_rotation_succeeded=True,
    )
    report = c.evaluate_secret(desc, _policy(), now=_NOW)
    assert report.worst is c.Verdict.PASS


def test_no_rotation_schedule_fails():
    desc = c.SecretDescriptor(
        name="dev/myapp/application",
        rotation_enabled=False,
        rotation_interval_days=None,
        last_rotated=None,
        tags={"owner": "team-a", "environment": "dev"},
    )
    report = c.evaluate_secret(desc, _policy(), now=_NOW)
    assert report.worst is c.Verdict.FAIL
    assert any(f.rule == "rotation_enabled" and f.verdict is c.Verdict.FAIL
               for f in report.findings)


def test_overdue_rotation_fails():
    desc = c.SecretDescriptor(
        name="dev/myapp/database",
        rotation_enabled=True,
        rotation_interval_days=30,
        last_rotated=_NOW - _dt.timedelta(days=120),
        tags={"owner": "team-a", "environment": "dev"},
        last_rotation_succeeded=True,
    )
    report = c.evaluate_secret(desc, _policy(), now=_NOW)
    assert report.worst is c.Verdict.FAIL
    assert any(f.rule == "overdue" and f.verdict is c.Verdict.FAIL for f in report.findings)


def test_missing_last_rotated_is_unknown_not_fail():
    """Missing data must be UNKNOWN, not a confirmed violation."""
    desc = c.SecretDescriptor(
        name="dev/myapp/database",
        rotation_enabled=True,
        rotation_interval_days=30,
        last_rotated=None,  # Secrets Manager did not report it
        tags={"owner": "team-a", "environment": "dev"},
        last_rotation_succeeded=True,
    )
    report = c.evaluate_secret(desc, _policy(), now=_NOW)
    overdue = [f for f in report.findings if f.rule == "overdue"]
    assert overdue and overdue[0].verdict is c.Verdict.UNKNOWN
    assert report.worst is c.Verdict.UNKNOWN


def test_missing_tags_fail():
    desc = c.SecretDescriptor(
        name="dev/myapp/database",
        rotation_enabled=True,
        rotation_interval_days=30,
        last_rotated=_NOW - _dt.timedelta(days=5),
        tags={"owner": "team-a"},  # missing "environment"
        last_rotation_succeeded=True,
    )
    report = c.evaluate_secret(desc, _policy(), now=_NOW)
    assert any(f.rule == "required_tags" and f.verdict is c.Verdict.FAIL
               for f in report.findings)


def test_failed_last_rotation_flagged():
    desc = c.SecretDescriptor(
        name="dev/myapp/database",
        rotation_enabled=True,
        rotation_interval_days=30,
        last_rotated=_NOW - _dt.timedelta(days=5),
        tags={"owner": "team-a", "environment": "dev"},
        last_rotation_succeeded=False,
    )
    report = c.evaluate_secret(desc, _policy(), now=_NOW)
    assert report.worst is c.Verdict.FAIL


def test_cert_near_expiry_fails():
    desc = c.SecretDescriptor(
        name="dev/myapp/tls",
        rotation_enabled=True,
        rotation_interval_days=30,
        last_rotated=_NOW - _dt.timedelta(days=5),
        tags={"owner": "team-a", "environment": "dev"},
        last_rotation_succeeded=True,
        cert_days_until_expiry=5,
    )
    report = c.evaluate_secret(desc, _policy(), now=_NOW)
    assert any(f.rule == "cert_expiry" and f.verdict is c.Verdict.FAIL
               for f in report.findings)


def test_aggregate_counts():
    descs = [
        c.SecretDescriptor("a", True, 30, _NOW, {"owner": "x", "environment": "dev"}, True),
        c.SecretDescriptor("b", False, None, None, {}, None),
    ]
    report = c.evaluate(descs, _policy(), now=_NOW)
    assert report.total == 2
    assert report.compliant == 1
    assert report.non_compliant == 1
