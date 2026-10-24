"""Certificate lifecycle management.

Renewing a certificate is fundamentally different from rotating a password or
API key:

* A password/API-key rotation *replaces a shared secret*. The old value becomes
  invalid once the new one is live.
* A certificate renewal *issues a new X.509 certificate* (usually a new keypair
  and a new validity window) signed by a CA. Trust is anchored in the CA, and
  clients accept any currently-valid, properly-signed certificate. There is no
  single "accepted value" at a remote provider to flip.

This module provides the operational pieces that work the same whether the cert
is issued by AWS Certificate Manager, cert-manager, or (for local demos only) a
self-signed CA:

* expiry inspection (``days_until_expiry``, ``needs_renewal``),
* chain / validity validation,
* a local self-signed issuance helper for controlled demonstrations.

For AWS-integrated TLS (ALB, CloudFront, API Gateway), prefer ACM: it renews
eligible certificates automatically and does NOT let you export the private key,
which is the secure default. We therefore never try to extract key material
from ACM. For in-cluster TLS, prefer cert-manager. Self-signed certs here are
labelled for local use only and must not be presented as production trust
anchors.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from ..logging_config import get_logger

logger = get_logger(__name__)

_UTC = _dt.UTC


@dataclass
class CertStatus:
    """Summary of a certificate's health for monitoring/alerting."""

    subject: str
    not_before: _dt.datetime
    not_after: _dt.datetime
    days_until_expiry: int
    needs_renewal: bool
    is_currently_valid: bool


def load_certificate(pem: bytes) -> x509.Certificate:
    """Parse a PEM-encoded certificate."""
    return x509.load_pem_x509_certificate(pem)


def days_until_expiry(cert: x509.Certificate, now: _dt.datetime | None = None) -> int:
    """Whole days from ``now`` until the certificate's ``notAfter``.

    Negative when the certificate has already expired.
    """
    now = now or _dt.datetime.now(_UTC)
    delta = cert.not_valid_after_utc - now
    return delta.days


def needs_renewal(
    cert: x509.Certificate, threshold_days: int = 30, now: _dt.datetime | None = None
) -> bool:
    """True if the cert expires within ``threshold_days`` (or already has)."""
    return days_until_expiry(cert, now) <= threshold_days


def status(
    cert: x509.Certificate, threshold_days: int = 30, now: _dt.datetime | None = None
) -> CertStatus:
    """Build a :class:`CertStatus` for monitoring."""
    now = now or _dt.datetime.now(_UTC)
    nb = cert.not_valid_before_utc
    na = cert.not_valid_after_utc
    return CertStatus(
        subject=cert.subject.rfc4514_string(),
        not_before=nb,
        not_after=na,
        days_until_expiry=days_until_expiry(cert, now),
        needs_renewal=needs_renewal(cert, threshold_days, now),
        is_currently_valid=nb <= now <= na,
    )


def validate_chain(leaf: x509.Certificate, issuer: x509.Certificate) -> bool:
    """Verify ``leaf`` was signed by ``issuer`` and is within its validity window.

    This is a focused check (signature + validity window), sufficient for the
    demo and policy checks. Full RFC 5280 path building/revocation is delegated
    to the TLS stack or the managed issuer in production.
    """
    now = _dt.datetime.now(_UTC)
    if not (leaf.not_valid_before_utc <= now <= leaf.not_valid_after_utc):
        return False
    issuer_public_key = issuer.public_key()
    # This focused check supports RSA issuers (what the demo CA uses). For other
    # key types, defer to the TLS stack / managed issuer rather than guess.
    if not isinstance(issuer_public_key, rsa.RSAPublicKey):
        return False
    try:
        # RSA issuer keys use PKCS1v15 padding with the cert's own hash alg.
        issuer_public_key.verify(
            leaf.signature,
            leaf.tbs_certificate_bytes,
            padding.PKCS1v15(),
            leaf.signature_hash_algorithm,  # type: ignore[arg-type]
        )
        return True
    except Exception:  # noqa: BLE001 — any verification error means "invalid"
        return False


def issue_self_signed(
    common_name: str,
    out_dir: str | Path,
    valid_days: int = 365,
    key_size: int = 2048,
) -> tuple[Path, Path]:
    """Issue a self-signed cert + key for LOCAL DEMONSTRATION ONLY.

    Writes ``<out_dir>/<cn>.key.pem`` (private key, 0600) and
    ``<out_dir>/<cn>.cert.pem``. Never use these as production trust anchors.

    Returns the ``(key_path, cert_path)`` tuple.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = _dt.datetime.now(_UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=1))
        .not_valid_after(now + _dt.timedelta(days=valid_days))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(common_name)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    key_path = out / f"{common_name}.key.pem"
    cert_path = out / f"{common_name}.cert.pem"
    key_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path.write_bytes(key_bytes)
    try:
        key_path.chmod(0o600)  # best-effort; no-op semantics on some Windows setups
    except OSError:
        pass
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    logger.info(
        "issued self-signed certificate for local demo",
        extra={"context": {"common_name": common_name, "valid_days": valid_days,
                           "cert_path": str(cert_path)}},
    )
    return key_path, cert_path


def issue_demo_cert_with_lifetime(
    common_name: str, out_dir: str | Path, valid_days: int
) -> tuple[Path, Path]:
    """Convenience wrapper to issue a cert with an explicit lifetime.

    Used by the failure/expiry demos to create an already-near-expiry cert.
    """
    return issue_self_signed(common_name, out_dir, valid_days=valid_days)
