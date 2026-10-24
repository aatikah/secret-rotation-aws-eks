# Database password rotation

Implemented in `src/secrets_rotation/rotation/database.py` (pure state machine),
`src/secrets_rotation/rotation/pg_connector.py` (real PostgreSQL), and
`lambda/database_rotation/handler.py` (Secrets Manager adapter).

## The four steps and why order matters

Secrets Manager invokes the rotation Lambda once per step. The order is not
arbitrary — each step depends on the previous one having succeeded.

1. **`createSecret`** — generate a high-entropy password with a CSPRNG and store
   it as a new `AWSPENDING` version. Idempotent: if a *rotated* pending version
   already exists for the rotation token, we don't mint another. This prevents a
   retried invocation from generating conflicting credentials.

2. **`setSecret`** — using the master login, apply the pending password to the
   target database user. **This is where the credential actually changes in the
   database**, not just in Secrets Manager. A workflow that skips this step would
   only change the stored string — a security no-op.

3. **`testSecret`** — open a real database connection as the pending user and run
   `SELECT 1`. If it fails, we raise and **do not proceed**. `AWSCURRENT` stays
   put and the application keeps using the still-valid current credential.

4. **`finishSecret`** — move `AWSCURRENT` to the pending version. The old version
   becomes `AWSPREVIOUS`, preserved for controlled recovery.

Reordering (e.g. promoting before testing) would risk handing applications an
unvalidated credential. The separation of `testSecret` from `finishSecret` is
precisely what guarantees "no silent promotion of invalid credentials."

## Alternating-users strategy

We rotate between two login roles — `myapp_a` and `myapp_b` — that share
privileges through a common NOLOGIN group role (e.g. `myapp`). At any time one
is active (referenced by `AWSCURRENT`) and the application uses it.

**How privileges stay in sync:** both users are granted the same group role, so
`GRANT`s applied to the group apply to both. `pg_connector.alter_user_password`
ensures the group exists, creates the inactive user if needed, sets its
password, and re-grants group membership on every rotation.

**Why not rotate a single user's password?** Changing one user's password
invalidates every live connection using the old password the instant it
changes — before the app has refreshed. The two-user model avoids that: the
active user is untouched during create/set/test; we only flip `AWSCURRENT` to
the newly-validated inactive user at the end.

**Rollback.** If `testSecret` fails, `AWSCURRENT` never moves, so rollback is
automatic — the app keeps using the previous user. Even after a successful
rotation, the previous version is retained as `AWSPREVIOUS`, and its login still
works until the *next* rotation changes it, giving a recovery window.

## On "zero downtime"

The alternating-users design *supports* a seamless cutover because the active
credential is valid throughout rotation. Whether an *already-running*
application sees zero downtime also depends on how it picks up the new value
(connection pool recycling, re-reading the secret). We do not claim zero
downtime beyond what the design and tests demonstrate: the local demo shows the
active credential never breaks mid-rotation, and the previous one survives for
recovery. Application refresh behaviour is addressed in the Kubernetes stage.

## Secret JSON shape

```json
{
  "engine": "postgres",
  "host": "...",
  "port": 5432,
  "dbname": "appdb",
  "username": "myapp_a",
  "password": "<generated>",
  "masterarn": "arn:aws:secretsmanager:...:secret:dev/myapp/database-master"
}
```

This matches the AWS "alternating users" rotation template so the same secret
works with the native rotation configuration in Stage 2.

## What is proven by tests

`tests/unit/test_database_rotation.py` covers: full rotation promotes the new
credential; the new credential authenticates; a failed `testSecret` does not
promote; `createSecret`/`finishSecret` are idempotent on retry; a stale,
un-staged token is refused (concurrent-safety); and generated passwords are
high-entropy and complex.
