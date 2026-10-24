# Certificate lifecycle management

Implemented in `src/secrets_rotation/rotation/certificates.py`.

## Renewal is not rotation

- **Rotating a password or API key** replaces a *shared secret*. The old value
  becomes invalid once the new one is live; there is a single "accepted value"
  at the target.
- **Renewing a certificate** issues a new X.509 certificate — usually a new
  keypair and a new validity window — signed by a Certificate Authority. Trust
  is anchored in the CA, and clients accept any currently-valid, properly-signed
  certificate. There is no single remote "accepted value" to flip.

Because of this, certificate handling is about *issuance, expiry monitoring,
renewal scheduling, deployment/reload, and validation* — not about promoting a
pending secret value.

## Capabilities provided

- `days_until_expiry` / `needs_renewal` — expiry inspection against a threshold.
- `status` — a `CertStatus` summary for monitoring/alerting (subject, validity
  window, days remaining, renewal flag, current validity).
- `validate_chain` — verifies a leaf was signed by a given issuer and is within
  its validity window (RSA issuers; full RFC 5280 path building/revocation is
  left to the TLS stack / managed issuer in production).
- `issue_self_signed` — issues a cert + key **for local demonstration only**,
  writing the private key with `0600` permissions.

## Choosing an issuer per environment

- **AWS-integrated TLS** (ALB, CloudFront, API Gateway): use **AWS Certificate
  Manager**. ACM renews eligible certificates automatically and does **not** let
  you export the private key — that is the secure default. We never attempt to
  extract key material from ACM.
- **In-cluster TLS**: use **cert-manager** to issue and renew certificates as
  Kubernetes resources.
- **Local demos only**: self-signed certs from `issue_self_signed`. These are
  explicitly **not** production trust anchors.

## Secure private-key handling

Private keys are written with restrictive permissions, never logged (the logger
redacts PEM private-key blocks — see `test_logging_redaction.py`), and never
committed (`.gitignore` blocks `*.pem`, `*.key`, and the `certs/` directory).

## What is proven by tests

`tests/unit/test_certificates.py`: issue + inspect a self-signed cert; a
near-expiry cert flags renewal; an expired cert is detected; a self-signed cert
validates against itself.
