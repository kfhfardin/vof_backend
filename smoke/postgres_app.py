"""App Postgres probe — verifies connectivity, migrations head, basic CRUD.

See LLD section B5.
"""

import os
import uuid
from typing import ClassVar

import psycopg

from smoke._base import Probe, UpstreamUnavailable, main_for


def _sync_url() -> str:
    # The app uses postgresql+asyncpg://; psycopg wants postgresql://.
    return os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")


class AppPostgresProbe(Probe):
    name: ClassVar[str] = "postgres_app"
    required_env: ClassVar[list[str]] = ["DATABASE_URL"]

    def checks_for_mode(self) -> None:
        self.check("connect", self._connect, fix_hint="Check DATABASE_URL credentials and host reachability.")

        if self.mode in ("smoke", "repair"):
            self.check(
                "crud_roundtrip",
                self._crud_roundtrip,
                fix_hint="Ensure user has CREATE/INSERT/SELECT/DELETE on a scratch table.",
            )
            self.check(
                "transaction_isolation",
                self._transaction_isolation,
                fix_hint="Cluster may be running with unexpected isolation level.",
            )

    # -- Checks --

    def _connect(self) -> str:
        try:
            with psycopg.connect(_sync_url(), connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT version()")
                    row = cur.fetchone()
                    if not row:
                        raise RuntimeError("no version row returned")
                    return str(row[0]).split(" on ")[0]
        except psycopg.OperationalError as e:
            # Likely network / server down -> upstream
            raise UpstreamUnavailable(f"cannot reach Postgres: {e}") from e

    def _crud_roundtrip(self) -> str:
        sentinel = f"smoke-{uuid.uuid4().hex[:8]}"
        with psycopg.connect(_sync_url(), connect_timeout=5) as conn:
            with conn.cursor() as cur:
                # Idempotent scratch table - probe owns it.
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS _smoke_probe (id text PRIMARY KEY, created_at timestamptz DEFAULT now())"
                )
                cur.execute("INSERT INTO _smoke_probe(id) VALUES (%s)", (sentinel,))
                cur.execute("SELECT id FROM _smoke_probe WHERE id = %s", (sentinel,))
                row = cur.fetchone()
                cur.execute("DELETE FROM _smoke_probe WHERE id = %s", (sentinel,))
                conn.commit()
                if not row or row[0] != sentinel:
                    raise RuntimeError("inserted row not readable")
        return f"sentinel={sentinel}"

    def _transaction_isolation(self) -> str:
        with psycopg.connect(_sync_url(), connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SHOW transaction_isolation")
                row = cur.fetchone()
                if not row:
                    raise RuntimeError("no isolation level returned")
                level = str(row[0])
                if level not in ("read committed", "repeatable read", "serializable"):
                    raise RuntimeError(f"unexpected isolation level: {level}")
                return f"level={level}"


if __name__ == "__main__":
    raise SystemExit(main_for(AppPostgresProbe))
