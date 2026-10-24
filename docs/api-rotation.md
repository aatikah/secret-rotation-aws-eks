# API credential rotation

Implemented in `src/secrets_rotation/rotation/api_credentials.py`.

## The distinction that matters most

Rotating an API credential means **changing it at the provider**, then
recording the new value in Secrets Manager — in that order. Simply overwriting
the stored string while the provider still accepts the old key is a security
no-op and is explicitly disallowed: `rotate_api_credential` requires
`provider.rotate_key()` to return a *new, different* key and will refuse to
record an empty or unchanged value.

## Safe transition workflow

1. Read the current key from `AWSCURRENT`.
2. Ask the provider to mint a replacement (**the real provider-side change**).
3. Store the replacement as `AWSPENDING`.
4. Validate the replacement is accepted by the provider.
5. Promote the pending version to `AWSCURRENT`.
6. Revoke the old key — **only** after a successful promotion.

On any failure before promotion, the new key is revoked (rollback) and the
stored `AWSCURRENT` is left untouched, so the application keeps using the key
that still works. Failures are returned as a `RotationResult` with
`status="rolled_back"` or raised — never silently swallowed.

## Overlapping vs non-overlapping providers

- **Overlapping** (`supports_overlap = True`): the new key is active while the
  old key still works for a grace period. This enables a seamless transition —
  create, validate, promote, then revoke the old key.
- **Non-overlapping** (`supports_overlap = False`): only one key can be active,
  so minting the new key invalidates the old one immediately. We narrow the
  window and report the brief invalidation via `RotationResult.had_overlap`
  rather than pretending it is zero-downtime.

## Providers without a rotation API

If a real provider exposes no programmatic rotation, that must be documented as
a **manual or provider-specific process** — not faked in code. The abstract
`ApiProvider` interface makes this explicit: a provider that cannot implement
`rotate_key` honestly should not be wired as automated. The mock provider used
in the demo and tests fully implements the contract so the end-to-end logic is
exercised without any real third-party credentials.

## What is proven by tests

`tests/unit/test_api_rotation.py`: successful rotation promotes and then revokes
the old key; failed validation rolls back and keeps the old key current; a
provider outage aborts without touching `AWSCURRENT`; and a non-overlapping
provider reports the transition correctly.
