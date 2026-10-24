"""Rotation-policy compliance checker.

Given a set of secret descriptors (metadata gathered from Secrets Manager via
``describe_secret`` + tags), evaluate each against a configurable policy and
produce a report. Thresholds come from a YAML policy file, not hardcoded, so
different environments can require different rotation intervals.

A key design principle: **distinguish missing data from a confirmed
violation.** AWS Secrets Manager does not always expose a reliable
"last rotated" timestamp (e.g. for secrets rotated out of band, or never
rotated). When the data needed to judge a rule is absent, the finding is
``UNKNOWN`` (needs manual action), not ``FAIL`` — reporting a false violation is
as harmful as missing a real one.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import yaml

_UTC = _dt.UTC


class Verdict(StrEnum):
    PASS = "PASS"  # noqa: S105 — enum label, not a credential
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"  # data missing; requires manual action


@dataclass
class SecretDescriptor:
    """Normalised view of a secret's metadata used for policy evaluation.

    All fields are non-secret. ``last_rotated`` may be ``None`` when Secrets
    Manager does not report it — that drives UNKNOWN, not FAIL.
    """

    name: str
    rotation_enabled: bool
    rotation_interval_days: int | None
    last_rotated: _dt.datetime | None
    tags: dict[str, str] = field(default_factory=dict)
    last_rotation_succeeded: bool | None = None
    cert_days_until_expiry: int | None = None  # for tls secrets only


@dataclass
class Finding:
    rule: str
    verdict: Verdict
    message: str


@dataclass
class SecretReport:
    name: str
    findings: list[Finding]

    @property
    def worst(self) -> Verdict:
        verdicts = {f.verdict for f in self.findings}
        if Verdict.FAIL in verdicts:
            return Verdict.FAIL
        if Verdict.UNKNOWN in verdicts:
            return Verdict.UNKNOWN
        return Verdict.PASS


@dataclass
class ComplianceReport:
    reports: list[SecretReport]

    @property
    def total(self) -> int:
        return len(self.reports)

    @property
    def compliant(self) -> int:
        return sum(1 for r in self.reports if r.worst is Verdict.PASS)

    @property
    def non_compliant(self) -> int:
        return sum(1 for r in self.reports if r.worst is Verdict.FAIL)

    @property
    def needs_manual_action(self) -> int:
        return sum(1 for r in self.reports if r.worst is Verdict.UNKNOWN)

    @property
    def rotation_failures(self) -> int:
        return sum(
            1
            for r in self.reports
            for f in r.findings
            if f.rule == "rotation_succeeded" and f.verdict is Verdict.FAIL
        )


@dataclass
class Policy:
    """Configurable policy thresholds."""

    max_rotation_interval_days: int = 90
    cert_expiry_warning_days: int = 30
    required_tags: tuple[str, ...] = ("owner", "environment")
    require_rotation_enabled: bool = True

    @classmethod
    def from_yaml(cls, path: str) -> Policy:
        with open(path, encoding="utf-8") as fh:
            data: dict[str, Any] = yaml.safe_load(fh) or {}
        return cls(
            max_rotation_interval_days=int(data.get("max_rotation_interval_days", 90)),
            cert_expiry_warning_days=int(data.get("cert_expiry_warning_days", 30)),
            required_tags=tuple(data.get("required_tags", ["owner", "environment"])),
            require_rotation_enabled=bool(data.get("require_rotation_enabled", True)),
        )


def evaluate_secret(
    desc: SecretDescriptor, policy: Policy, now: _dt.datetime | None = None
) -> SecretReport:
    """Evaluate one secret against the policy and return its findings."""
    now = now or _dt.datetime.now(_UTC)
    findings: list[Finding] = []

    # Rule: rotation must be configured.
    if policy.require_rotation_enabled:
        if desc.rotation_enabled:
            findings.append(Finding("rotation_enabled", Verdict.PASS, "rotation is enabled"))
        else:
            findings.append(
                Finding("rotation_enabled", Verdict.FAIL, "no rotation schedule configured")
            )

    # Rule: rotation interval must not exceed the policy maximum.
    if desc.rotation_interval_days is None:
        findings.append(
            Finding(
                "rotation_interval",
                Verdict.UNKNOWN if desc.rotation_enabled else Verdict.FAIL,
                "rotation interval not reported",
            )
        )
    elif desc.rotation_interval_days > policy.max_rotation_interval_days:
        findings.append(
            Finding(
                "rotation_interval",
                Verdict.FAIL,
                f"interval {desc.rotation_interval_days}d exceeds max "
                f"{policy.max_rotation_interval_days}d",
            )
        )
    else:
        findings.append(Finding("rotation_interval", Verdict.PASS, "within policy"))

    # Rule: must not be overdue. Missing last_rotated => UNKNOWN, not FAIL.
    if desc.last_rotated is None:
        findings.append(
            Finding(
                "overdue",
                Verdict.UNKNOWN,
                "no last-rotated timestamp available; cannot confirm freshness",
            )
        )
    elif desc.rotation_interval_days is not None:
        age_days = (now - desc.last_rotated).days
        if age_days > desc.rotation_interval_days:
            findings.append(
                Finding(
                    "overdue",
                    Verdict.FAIL,
                    f"last rotated {age_days}d ago, exceeds interval "
                    f"{desc.rotation_interval_days}d",
                )
            )
        else:
            findings.append(Finding("overdue", Verdict.PASS, f"rotated {age_days}d ago"))

    # Rule: last rotation must not have failed.
    if desc.last_rotation_succeeded is False:
        findings.append(
            Finding("rotation_succeeded", Verdict.FAIL, "last rotation attempt failed")
        )
    elif desc.last_rotation_succeeded is True:
        findings.append(
            Finding("rotation_succeeded", Verdict.PASS, "last rotation succeeded")
        )

    # Rule: required ownership/environment tags present.
    missing = [t for t in policy.required_tags if t not in desc.tags or not desc.tags[t]]
    if missing:
        findings.append(
            Finding("required_tags", Verdict.FAIL, f"missing tags: {', '.join(missing)}")
        )
    else:
        findings.append(Finding("required_tags", Verdict.PASS, "all required tags present"))

    # Rule: certificate expiry (tls secrets only).
    if desc.cert_days_until_expiry is not None:
        if desc.cert_days_until_expiry <= 0:
            findings.append(
                Finding("cert_expiry", Verdict.FAIL, "certificate has expired")
            )
        elif desc.cert_days_until_expiry <= policy.cert_expiry_warning_days:
            findings.append(
                Finding(
                    "cert_expiry",
                    Verdict.FAIL,
                    f"certificate expires in {desc.cert_days_until_expiry}d "
                    f"(threshold {policy.cert_expiry_warning_days}d)",
                )
            )
        else:
            findings.append(
                Finding(
                    "cert_expiry",
                    Verdict.PASS,
                    f"certificate valid for {desc.cert_days_until_expiry}d",
                )
            )

    return SecretReport(name=desc.name, findings=findings)


def evaluate(
    descriptors: list[SecretDescriptor], policy: Policy, now: _dt.datetime | None = None
) -> ComplianceReport:
    """Evaluate a list of secrets and aggregate the results."""
    return ComplianceReport(
        reports=[evaluate_secret(d, policy, now) for d in descriptors]
    )
