"""initial brain schema placeholder — pgvector extension

Revision ID: 0001_initial_brain
Revises:
Create Date: 2026-05-16

Brain-side models land with §C8 (provenance + page versioning) and §D3
(typed graph). This initial migration only ensures pgvector is enabled —
the schema-per-Workspace mechanics happen at runtime per workspace,
not in this global migration.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_initial_brain"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Keep pgvector around; dropping it would orphan any data
    pass
