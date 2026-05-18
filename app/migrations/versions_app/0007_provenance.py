"""provenance table

Revision ID: 0007_provenance
Revises: 0006_decision_requests
Create Date: 2026-05-17

Per HLD §9.1 every brain write carries a provenance row. Lives in the app
DB rather than the per-workspace brain schema so it can be looked up from
API endpoints without hopping schemas. Brain pages reference provenance.id
by UUID without an enforced cross-DB FK.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_provenance"
down_revision: str | None = "0006_decision_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provenance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("extracted_by", sa.String(length=128), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "cites",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["manager_workspaces.id"],
            name="fk_provenance_workspace_id_manager_workspaces",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "source_type IN ('manager_form','manager_upload','manager_voice_intake',"
            "'manager_correction','field_call','automated_extraction',"
            "'external_research','system_seed')",
            name="source_type",
        ),
    )
    op.create_index("ix_provenance_workspace_id", "provenance", ["workspace_id"])
    op.create_index("ix_provenance_source_type", "provenance", ["source_type"])
    op.create_index("ix_provenance_source_id", "provenance", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_provenance_source_id", table_name="provenance")
    op.drop_index("ix_provenance_source_type", table_name="provenance")
    op.drop_index("ix_provenance_workspace_id", table_name="provenance")
    op.drop_table("provenance")
