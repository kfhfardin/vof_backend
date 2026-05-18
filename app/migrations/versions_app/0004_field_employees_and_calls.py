"""field employees + calls tables

Revision ID: 0004_field_employees_and_calls
Revises: 0003_intake_buffer_items
Create Date: 2026-05-17

Phase 0 §C3 - the AgentPhone webhook needs Call rows to record lifecycle
and FieldEmployee rows to map inbound numbers to known Reps.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_field_employees_and_calls"
down_revision: str | None = "0003_intake_buffer_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "field_employees",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=120), nullable=True),
        sa.Column("team", sa.String(length=120), nullable=True),
        sa.Column("profiled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("supermemory_user_id", sa.String(length=128), nullable=True),
        sa.Column(
            "profile",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["manager_workspaces.id"],
            name="fk_field_employees_workspace_id_manager_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_field_employees_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("workspace_id", "phone", name="uq_field_employees_workspace_phone"),
    )
    op.create_index("ix_field_employees_workspace_id", "field_employees", ["workspace_id"])
    op.create_index("ix_field_employees_organization_id", "field_employees", ["organization_id"])
    op.create_index("ix_field_employees_user_id", "field_employees", ["user_id"])

    op.create_table(
        "calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field_employee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agentphone_call_id", sa.String(length=64), nullable=False),
        sa.Column("from_number", sa.String(length=32), nullable=True),
        sa.Column("to_number", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'ringing'"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recording_uri", sa.String(length=1024), nullable=True),
        sa.Column("transcript_uri", sa.String(length=1024), nullable=True),
        sa.Column("provider_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["manager_workspaces.id"],
            name="fk_calls_workspace_id_manager_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_calls_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["field_employee_id"],
            ["field_employees.id"],
            name="fk_calls_field_employee_id_field_employees",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("agentphone_call_id", name="uq_calls_agentphone_call_id"),
        sa.CheckConstraint(
            "status IN ('ringing','in_progress','ended','failed')",
            name="status",
        ),
    )
    op.create_index("ix_calls_workspace_id", "calls", ["workspace_id"])
    op.create_index("ix_calls_organization_id", "calls", ["organization_id"])
    op.create_index("ix_calls_field_employee_id", "calls", ["field_employee_id"])
    op.create_index("ix_calls_status", "calls", ["status"])


def downgrade() -> None:
    op.drop_index("ix_calls_status", table_name="calls")
    op.drop_index("ix_calls_field_employee_id", table_name="calls")
    op.drop_index("ix_calls_organization_id", table_name="calls")
    op.drop_index("ix_calls_workspace_id", table_name="calls")
    op.drop_table("calls")
    op.drop_index("ix_field_employees_user_id", table_name="field_employees")
    op.drop_index("ix_field_employees_organization_id", table_name="field_employees")
    op.drop_index("ix_field_employees_workspace_id", table_name="field_employees")
    op.drop_table("field_employees")
