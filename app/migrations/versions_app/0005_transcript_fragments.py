"""transcript fragments table

Revision ID: 0005_transcript_fragments
Revises: 0004_field_employees_and_calls
Create Date: 2026-05-17

Per LLD §C4 - one row per speaker turn within a Call. Powers post-call
summarization (§C11) and the multi-call live view (§C5).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_transcript_fragments"
down_revision: str | None = "0004_field_employees_and_calls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transcript_fragments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("speaker", sa.String(length=8), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name="fk_transcript_fragments_call_id_calls",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["manager_workspaces.id"],
            name="fk_transcript_fragments_workspace_id_manager_workspaces",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("speaker IN ('caller','agent')", name="speaker"),
        sa.UniqueConstraint("call_id", "seq", name="uq_transcript_fragments_call_id_seq"),
    )
    op.create_index("ix_transcript_fragments_call_id", "transcript_fragments", ["call_id"])
    op.create_index(
        "ix_transcript_fragments_workspace_id",
        "transcript_fragments",
        ["workspace_id"],
    )
    op.create_index("ix_transcript_fragments_ts", "transcript_fragments", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_transcript_fragments_ts", table_name="transcript_fragments")
    op.drop_index("ix_transcript_fragments_workspace_id", table_name="transcript_fragments")
    op.drop_index("ix_transcript_fragments_call_id", table_name="transcript_fragments")
    op.drop_table("transcript_fragments")
