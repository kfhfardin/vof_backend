"""initial app schema — organizations, manager_workspaces, users

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-16

Creates the Phase 0 hierarchy backbone (HLD §6, LLD §C1, §C10):
  - organizations  (auto-created per Manager signup)
  - manager_workspaces (the unit of isolation)
  - users (role enum supports all 4 future roles)

The Workspace -> User FK is added with use_alter=True since the two
tables reference each other; deferring the constraint lets us create
both tables before adding the cross-reference.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
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
    )

    op.create_table(
        "manager_workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        # manager_user_id FK added via alter after `users` table exists
        sa.Column("manager_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("primary_number", sa.String(length=32), nullable=True),
        sa.Column("agentphone_agent_id", sa.String(length=64), nullable=True),
        sa.Column("agentphone_number_id", sa.String(length=64), nullable=True),
        sa.Column(
            "provisioning_state",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
            ["organization_id"],
            ["organizations.id"],
            name="fk_manager_workspaces_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("primary_number", name="uq_manager_workspaces_primary_number"),
    )
    op.create_index(
        "ix_manager_workspaces_organization_id",
        "manager_workspaces",
        ["organization_id"],
    )
    op.create_index(
        "ix_manager_workspaces_manager_user_id",
        "manager_workspaces",
        ["manager_user_id"],
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("field_employee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("front_end_push_token", sa.String(length=256), nullable=True),
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
            ["organization_id"],
            ["organizations.id"],
            name="fk_users_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["manager_workspaces.id"],
            name="fk_users_workspace_id_manager_workspaces",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
        # Schema-level role check: enforces the four-role enum from day one
        # so the §C10 guard test has something to bind against.
        sa.CheckConstraint(
            "role IN ('manager', 'org_admin', 'rep', 'viewer')",
            name="role",
        ),
    )
    op.create_index("ix_users_organization_id", "users", ["organization_id"])
    op.create_index("ix_users_workspace_id", "users", ["workspace_id"])
    op.create_index("ix_users_field_employee_id", "users", ["field_employee_id"])
    op.create_index("ix_users_role", "users", ["role"])

    # Now the back-reference from manager_workspaces -> users
    op.create_foreign_key(
        "fk_manager_workspaces_manager_user_id_users",
        "manager_workspaces",
        "users",
        ["manager_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_manager_workspaces_manager_user_id_users",
        "manager_workspaces",
        type_="foreignkey",
    )
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_field_employee_id", table_name="users")
    op.drop_index("ix_users_workspace_id", table_name="users")
    op.drop_index("ix_users_organization_id", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_manager_workspaces_manager_user_id", table_name="manager_workspaces")
    op.drop_index("ix_manager_workspaces_organization_id", table_name="manager_workspaces")
    op.drop_table("manager_workspaces")
    op.drop_table("organizations")
