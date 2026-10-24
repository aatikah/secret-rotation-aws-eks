"""Command-line interface for the secrets rotation platform.

Subcommands:
    policy-check   Evaluate secrets against the rotation policy and print a report.
    audit-report   Summarise CloudTrail events (from a JSON file or live lookup).
    cw-queries     Print ready-to-use CloudWatch / CloudTrail investigation queries.

The CLI reads secret *metadata* only (never values). ``policy-check`` and
``audit-report`` take a JSON ``--input`` file: export live secret descriptors or
CloudTrail events from AWS (e.g. ``aws cloudtrail lookup-events``) and feed them
in. This keeps the CLI composable with the AWS CLI while never handling secret
values.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from typing import Any

import click

from .audit import reporting
from .config import Settings
from .logging_config import configure_logging
from .policy import compliance

_UTC = _dt.UTC


def _parse_dt(value: str | None) -> _dt.datetime | None:
    if not value:
        return None
    return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _descriptor_from_json(obj: dict[str, Any]) -> compliance.SecretDescriptor:
    return compliance.SecretDescriptor(
        name=obj["name"],
        rotation_enabled=bool(obj.get("rotation_enabled", False)),
        rotation_interval_days=obj.get("rotation_interval_days"),
        last_rotated=_parse_dt(obj.get("last_rotated")),
        tags=dict(obj.get("tags", {})),
        last_rotation_succeeded=obj.get("last_rotation_succeeded"),
        cert_days_until_expiry=obj.get("cert_days_until_expiry"),
    )


@click.group()
@click.option("--log-level", default=None, help="Override log level (DEBUG/INFO/WARNING/ERROR).")
@click.pass_context
def cli(ctx: click.Context, log_level: str | None) -> None:
    """Secrets rotation platform CLI."""
    settings = Settings()
    configure_logging(level=log_level or settings.log_level)
    ctx.obj = {"settings": settings}


@cli.command("policy-check")
@click.option(
    "--input", "input_path", type=click.Path(exists=True, dir_okay=False),
    help="JSON file with a list of secret descriptors (offline mode).",
)
@click.option(
    "--policy", "policy_path", type=click.Path(exists=True, dir_okay=False),
    default=None, help="Policy YAML file (defaults to POLICY_FILE / config).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit the report as JSON.")
@click.pass_context
def policy_check(
    ctx: click.Context, input_path: str | None, policy_path: str | None, as_json: bool
) -> None:
    """Evaluate secrets against the rotation policy and print a compliance report."""
    settings: Settings = ctx.obj["settings"]
    policy = compliance.Policy.from_yaml(policy_path or settings.policy_file)

    if input_path:
        with open(input_path, encoding="utf-8") as fh:
            raw = json.load(fh)
        descriptors = [_descriptor_from_json(o) for o in raw]
    else:
        raise click.ClickException(
            "live AWS mode is not wired in Stage 1; pass --input <fixture.json>. "
            "A later stage adds a describe_secrets collector."
        )

    report = compliance.evaluate(descriptors, policy, now=_dt.datetime.now(_UTC))

    if as_json:
        click.echo(json.dumps(_report_to_dict(report), indent=2, default=str))
    else:
        _print_report(report)

    # Non-zero exit when there is a confirmed violation, so CI can gate on it.
    sys.exit(1 if report.non_compliant > 0 else 0)


@cli.command("audit-report")
@click.option(
    "--input", "input_path", type=click.Path(exists=True, dir_okay=False), required=True,
    help="JSON file containing a list of CloudTrail event records.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit the summary as JSON.")
def audit_report(input_path: str, as_json: bool) -> None:
    """Summarise CloudTrail Secrets Manager events from a JSON file."""
    with open(input_path, encoding="utf-8") as fh:
        records = json.load(fh)
    summary = reporting.summarise(records)

    if as_json:
        click.echo(
            json.dumps(
                {
                    "rotation_events": summary.rotation_events,
                    "read_events": summary.read_events,
                    "errors": summary.errors,
                    "by_event": dict(summary.by_event),
                    "by_principal": dict(summary.by_principal),
                },
                indent=2,
            )
        )
    else:
        click.echo("=== Audit summary ===")
        click.echo(f"Rotation events : {summary.rotation_events}")
        click.echo(f"Read events     : {summary.read_events}")
        click.echo(f"Errors          : {summary.errors}")
        click.echo("By event:")
        for name, count in summary.by_event.most_common():
            click.echo(f"  {name}: {count}")
        click.echo("By principal:")
        for name, count in summary.by_principal.most_common():
            click.echo(f"  {name}: {count}")


@cli.command("cw-queries")
def cw_queries() -> None:
    """Print example CloudWatch Logs Insights / CloudTrail investigation queries."""
    click.echo("# Failed rotations (CloudWatch Logs Insights)\n")
    click.echo(reporting.CW_QUERY_FAILED_ROTATIONS)
    click.echo("\n# Rotation duration (CloudWatch Logs Insights)\n")
    click.echo(reporting.CW_QUERY_ROTATION_DURATION)
    click.echo("\n# Unusual access (CloudTrail Lake / Athena)\n")
    click.echo(reporting.CT_QUERY_UNUSUAL_ACCESS)


def _report_to_dict(report: compliance.ComplianceReport) -> dict[str, Any]:
    return {
        "summary": {
            "total": report.total,
            "compliant": report.compliant,
            "non_compliant": report.non_compliant,
            "needs_manual_action": report.needs_manual_action,
            "rotation_failures": report.rotation_failures,
        },
        "secrets": [
            {
                "name": r.name,
                "verdict": r.worst.value,
                "findings": [
                    {"rule": f.rule, "verdict": f.verdict.value, "message": f.message}
                    for f in r.findings
                ],
            }
            for r in report.reports
        ],
    }


def _print_report(report: compliance.ComplianceReport) -> None:
    click.echo("=== Rotation policy compliance report ===")
    click.echo(f"Total assessed       : {report.total}")
    click.echo(f"Compliant            : {report.compliant}")
    click.echo(f"Non-compliant        : {report.non_compliant}")
    click.echo(f"Needs manual action  : {report.needs_manual_action}")
    click.echo(f"Rotation failures    : {report.rotation_failures}")
    click.echo("")
    for r in report.reports:
        marker = {"PASS": "OK ", "FAIL": "XX ", "UNKNOWN": "?? "}[r.worst.value]
        click.echo(f"[{marker}] {r.name}  ({r.worst.value})")
        for f in r.findings:
            if f.verdict is not compliance.Verdict.PASS:
                click.echo(f"       - {f.rule}: {f.message} [{f.verdict.value}]")


def main() -> None:
    """Entry point referenced by the ``secrets-rotation`` console script."""
    cli()


if __name__ == "__main__":
    main()
