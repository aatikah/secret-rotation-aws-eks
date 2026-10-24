"""Real PostgreSQL connector used by the rotation state machine.

Isolated from :mod:`secrets_rotation.rotation.database` so that the psycopg
import happens only where a real connection is required — the rotation Lambda
running against the RDS database in AWS, and the AWS integration tests that run
against that same deployed database.

Connection handling notes
-------------------------
* We connect with an explicit short timeout so a transient network issue
  surfaces quickly rather than hanging the Lambda until it times out.
* Identifiers (role names) are quoted via ``psycopg.sql`` to prevent SQL
  injection through a username. Passwords are passed as values, never
  f-string-interpolated into the statement.
* Nothing here logs a password or a DSN containing one.
"""

from __future__ import annotations

from typing import Any

from .database import DbConnector

# connect timeout (seconds) for every connection attempt.
_CONNECT_TIMEOUT = 5


class PostgresConnector(DbConnector):
    """psycopg-backed implementation of :class:`DbConnector`."""

    def __init__(self, connect_timeout: int = _CONNECT_TIMEOUT) -> None:
        self._connect_timeout = connect_timeout

    def _connect(self, credentials: dict[str, Any]) -> Any:
        import psycopg  # imported lazily; see module docstring

        return psycopg.connect(
            host=credentials["host"],
            port=int(credentials.get("port", 5432)),
            dbname=credentials["dbname"],
            user=credentials["username"],
            password=credentials["password"],
            connect_timeout=self._connect_timeout,
            sslmode="require",
            autocommit=True,
        )

    def alter_user_password(
        self, master: dict[str, Any], username: str, new_password: str
    ) -> None:
        """Create the role if missing and set its password, as the master user.

        The role is granted membership of the application role group so both
        alternating users share identical privileges. Adjust ``app_group`` to
        your schema; the default mirrors the ``<app>`` prefix of the username.
        """
        import psycopg
        from psycopg import sql

        app_group = username.rsplit("_", 1)[0]  # myapp_a -> myapp
        with self._connect(master) as conn, conn.cursor() as cur:
            # Ensure the shared privilege group exists.
            cur.execute(
                sql.SQL("SELECT 1 FROM pg_roles WHERE rolname = {grp}").format(
                    grp=sql.Literal(app_group)
                )
            )
            if cur.fetchone() is None:
                cur.execute(
                    sql.SQL("CREATE ROLE {grp} NOLOGIN").format(
                        grp=sql.Identifier(app_group)
                    )
                )

            # Ensure the login role exists, then set password + group membership.
            cur.execute(
                sql.SQL("SELECT 1 FROM pg_roles WHERE rolname = {u}").format(
                    u=sql.Literal(username)
                )
            )
            exists = cur.fetchone() is not None
            if exists:
                cur.execute(
                    sql.SQL("ALTER ROLE {u} WITH LOGIN PASSWORD {pw}").format(
                        u=sql.Identifier(username), pw=sql.Literal(new_password)
                    )
                )
            else:
                cur.execute(
                    sql.SQL("CREATE ROLE {u} WITH LOGIN PASSWORD {pw}").format(
                        u=sql.Identifier(username), pw=sql.Literal(new_password)
                    )
                )
            cur.execute(
                sql.SQL("GRANT {grp} TO {u}").format(
                    grp=sql.Identifier(app_group), u=sql.Identifier(username)
                )
            )
        _ = psycopg  # keep import referenced for linters

    def can_authenticate(self, credentials: dict[str, Any]) -> bool:
        """Open a connection with ``credentials`` and run ``SELECT 1``.

        Returns False on an authentication failure; re-raises on unexpected
        operational errors so the caller can distinguish "wrong password" from
        "database unreachable" and apply retry logic appropriately.
        """
        import psycopg

        try:
            with self._connect(credentials) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone() == (1,)
        except psycopg.OperationalError as exc:
            # 28P01 = invalid_password, 28000 = invalid_authorization_specification
            sqlstate = getattr(exc, "sqlstate", None)
            if sqlstate in {"28P01", "28000"}:
                return False
            raise
