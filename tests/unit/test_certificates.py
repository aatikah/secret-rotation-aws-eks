"""Unit tests for certificate lifecycle helpers."""

from __future__ import annotations

import datetime as _dt

from secrets_rotation.rotation import certificates as certs

_UTC = _dt.UTC


def test_issue_and_inspect_self_signed(tmp_path):
    key_path, cert_path = certs.issue_self_signed("demo.local", tmp_path, valid_days=365)
    assert key_path.exists() and cert_path.exists()

    cert = certs.load_certificate(cert_path.read_bytes())
    st = certs.status(cert, threshold_days=30)
    assert st.is_currently_valid is True
    assert st.needs_renewal is False
    assert st.days_until_expiry > 300


def test_near_expiry_cert_flags_renewal(tmp_path):
    _, cert_path = certs.issue_demo_cert_with_lifetime("expiring.local", tmp_path, valid_days=10)
    cert = certs.load_certificate(cert_path.read_bytes())
    assert certs.needs_renewal(cert, threshold_days=30) is True


def test_expired_cert_detection(tmp_path):
    _, cert_path = certs.issue_self_signed("x.local", tmp_path, valid_days=365)
    cert = certs.load_certificate(cert_path.read_bytes())
    # Evaluate as if "now" is two years in the future.
    future = _dt.datetime.now(_UTC) + _dt.timedelta(days=730)
    assert certs.days_until_expiry(cert, now=future) < 0
    assert certs.needs_renewal(cert, threshold_days=30, now=future) is True


def test_self_signed_cert_validates_against_itself(tmp_path):
    _, cert_path = certs.issue_self_signed("self.local", tmp_path, valid_days=365)
    cert = certs.load_certificate(cert_path.read_bytes())
    # A self-signed cert is its own issuer, so chain validation succeeds.
    assert certs.validate_chain(cert, cert) is True
