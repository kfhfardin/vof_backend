"""call artifacts table

Revision ID: 0008_call_artifacts
Revises: 0007_provenance
Create Date: 2026-05-17

Per LLD §C11. One row per stored byproduct of a call (canonical_summary,
transcript, recording, ...). The blob lives in object storage; this row
holds the metadata for FE listing + download.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_call_artifacts"
down_revision: str | None = "0007_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "call_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name="fk_call_artifacts_call_id_calls",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["manager_workspaces.id"],
            name="fk_call_artifacts_workspace_id_manager_workspaces",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "kind IN ('canonical_summary','transcript','recording','provider_summary','action_items_export')",
            name="kind",
        ),
    )
    op.create_index("ix_call_artifacts_call_id", "call_artifacts", ["call_id"])
    op.create_index("ix_call_artifacts_workspace_id", "call_artifacts", ["workspace_id"])
    op.create_index("ix_call_artifacts_kind", "call_artifacts", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_call_artifacts_kind", table_name="call_artifacts")
    op.drop_index("ix_call_artifacts_workspace_id", table_name="call_artifacts")
    op.drop_index("ix_call_artifacts_call_id", table_name="call_artifacts")
    op.drop_table("call_artifacts")
