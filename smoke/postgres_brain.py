"""Brain Postgres probe - pgvector + schema-per-Workspace round-trip.

See LLD section B6.
"""

import os
import uuid
from typing import ClassVar

import psycopg

from smoke._base import Probe, UpstreamUnavailable, main_for


def _sync_url() -> str:
    return os.environ["BRAIN_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")


class BrainPostgresProbe(Probe):
    name: ClassVar[str] = "postgres_brain"
    required_env: ClassVar[list[str]] = ["BRAIN_DATABASE_URL"]

    def checks_for_mode(self) -> None:
        self.check("connect", self._connect, fix_hint="Check BRAIN_DATABASE_URL.")
        self.check(
            "pgvector_present",
            self._pgvector_present,
            fix_hint="Run: CREATE EXTENSION IF NOT EXISTS vector;",
        )
        self.check(
            "tsvector_works",
            self._tsvector_works,
            fix_hint="tsvector is built into Postgres; if missing, your install is unusually broken.",
        )

        if self.mode in ("smoke", "repair"):
            schema = f"brain_w_smoketest_{uuid.uuid4().hex[:12]}"
            try:
                self.check(
                    "schema_per_workspace_create",
                    lambda: self._create_test_schema(schema),
                    fix_hint="DB user needs CREATE on database.",
                )
                self.check(
                    "embedding_roundtrip",
                    lambda: self._embedding_roundtrip(schema),
                    fix_hint="Vector type or index may not be available.",
                )
            finally:
                # Always attempt cleanup, even on prior failure
                self.check(
                    "schema_per_workspace_drop",
                    lambda: self._drop_test_schema(schema),
                )

    # -- Checks --

    def _connect(self) -> str:
        try:
            with psycopg.connect(_sync_url(), connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
                    return "ok"
        except psycopg.OperationalError as e:
            raise UpstreamUnavailable(f"cannot reach brain Postgres: {e}") from e

    def _pgvector_present(self) -> str:
        with psycopg.connect(_sync_url(), connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                row = cur.fetchone()
                if not row:
                    raise RuntimeError("pgvector not installed in this database")
                return f"extname={row[0]}"

    def _tsvector_works(self) -> str:
        with psycopg.connect(_sync_url(), connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_tsvector('english', 'hello world')")
                row = cur.fetchone()
                if not row or not row[0]:
                    raise RuntimeError("tsvector returned empty")
                return "tsvector ok"

    def _create_test_schema(self, schema: str) -> str:
        with psycopg.connect(_sync_url(), connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA "{schema}"')
                conn.commit()
                return f"schema={schema}"

    def _embedding_roundtrip(self, schema: str) -> str:
        # Insert a row with a vector + tsvector; query it back.
        with psycopg.connect(_sync_url(), connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'CREATE TABLE "{schema}".scratch (id serial PRIMARY KEY, '
                    f"body text, embedding vector(8), tsv tsvector)"
                )
                vec = "[" + ",".join([f"{i / 10:.2f}" for i in range(8)]) + "]"
                cur.execute(
                    f'INSERT INTO "{schema}".scratch(body, embedding, tsv) '
                    f"VALUES (%s, %s::vector, to_tsvector('english', %s))",
                    ("hello vector world", vec, "hello vector world"),
                )
                cur.execute(
                    f'SELECT id, body FROM "{schema}".scratch '
                    f"WHERE tsv @@ plainto_tsquery('english', 'vector')"
                )
                row = cur.fetchone()
                if not row:
                    raise RuntimeError("inserted row not searchable via tsvector")
                # Quick vector distance query
                cur.execute(
                    f'SELECT id FROM "{schema}".scratch ORDER BY embedding <-> %s::vector LIMIT 1',
                    (vec,),
                )
                vec_row = cur.fetchone()
                if not vec_row:
                    raise RuntimeError("vector distance query returned no row")
                conn.commit()
                return f"id={row[0]} body={row[1]!r}"

    def _drop_test_schema(self, schema: str) -> str:
        with psycopg.connect(_sync_url(), connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                conn.commit()
                return f"dropped {schema}"


if __name__ == "__main__":
    raise SystemExit(main_for(BrainPostgresProbe))
