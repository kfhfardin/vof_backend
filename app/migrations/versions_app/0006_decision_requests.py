"""decision requests table

Revision ID: 0006_decision_requests
Revises: 0005_transcript_fragments
Create Date: 2026-05-17

Per LLD §C6 / HLD §5.5.3. Three decision classes (inline/bridged/async),
four lifecycle states (open/answered/timed_out/cancelled), audit columns
for who/when/via, surfaced_in_brief_at for §C7 + §D5 brief flagging.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_decision_requests"
down_revision: str | None = "0005_transcript_fragments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decision_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decision_class", sa.String(length=16), nullable=False),
        sa.Column("timeout_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("responded_via", sa.String(length=16), nullable=True),
        sa.Column("surfaced_in_brief_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
            name="fk_decision_requests_call_id_calls",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["manager_workspaces.id"],
            name="fk_decision_requests_workspace_id_manager_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name="fk_decision_requests_target_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["responded_by_user_id"],
            ["users.id"],
            name="fk_decision_requests_responded_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "decision_class IN ('inline','bridged','async')",
            name="decision_class",
        ),
        sa.CheckConstraint(
            "status IN ('open','answered','timed_out','cancelled')",
            name="status",
        ),
        sa.CheckConstraint(
            "responded_via IS NULL OR responded_via IN ('websocket','sms','timeout')",
            name="responded_via",
        ),
    )
    op.create_index("ix_decision_requests_call_id", "decision_requests", ["call_id"])
    op.create_index("ix_decision_requests_workspace_id", "decision_requests", ["workspace_id"])
    op.create_index("ix_decision_requests_target_user_id", "decision_requests", ["target_user_id"])
    op.create_index("ix_decision_requests_status", "decision_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_decision_requests_status", table_name="decision_requests")
    op.drop_index("ix_decision_requests_target_user_id", table_name="decision_requests")
    op.drop_index("ix_decision_requests_workspace_id", table_name="decision_requests")
    op.drop_index("ix_decision_requests_call_id", table_name="decision_requests")
    op.drop_table("decision_requests")
