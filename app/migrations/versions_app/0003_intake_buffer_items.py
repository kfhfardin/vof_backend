"""intake buffer items table

Revision ID: 0003_intake_buffer_items
Revises: 0002_refresh_tokens
Create Date: 2026-05-16

Per LLD §C2 - one table for every Manager-driven intake event:
form submissions, document uploads, voice-intake transcript chunks,
corrections. Powers both onboarding and continuous updates.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_intake_buffer_items"
down_revision: str | None = "0002_refresh_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intake_buffer_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submitted_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("content_blob_key", sa.String(length=512), nullable=True),
        sa.Column("content_mime", sa.String(length=128), nullable=True),
        sa.Column("content_filename", sa.String(length=255), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("extractor_used", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("classification", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("handler_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("superseded_by_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
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
            ["workspace_id"],
            ["manager_workspaces.id"],
            name="fk_intake_buffer_items_workspace_id_manager_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_intake_buffer_items_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_user_id"],
            ["users.id"],
            name="fk_intake_buffer_items_submitted_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_item_id"],
            ["intake_buffer_items.id"],
            # Shortened; Postgres caps identifiers at 63 bytes.
            name="fk_intake_buffer_items_superseded_by_item_id",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "source IN ('form', 'upload', 'voice_intake', 'correction')",
            name="source",
        ),
        sa.CheckConstraint(
            "purpose IN ('onboarding', 'ongoing_update', 'correction')",
            name="purpose",
        ),
        sa.CheckConstraint(
            "status IN ('queued','extracting','classified','ingested','needs_review','failed','superseded','deleted')",
            name="status",
        ),
    )
    op.create_index(
        "ix_intake_buffer_items_workspace_id", "intake_buffer_items", ["workspace_id"]
    )
    op.create_index(
        "ix_intake_buffer_items_organization_id", "intake_buffer_items", ["organization_id"]
    )
    op.create_index("ix_intake_buffer_items_status", "intake_buffer_items", ["status"])
    op.create_index("ix_intake_buffer_items_content_sha256", "intake_buffer_items", ["content_sha256"])
    op.create_index(
        "ix_intake_buffer_items_superseded_by_item_id",
        "intake_buffer_items",
        ["superseded_by_item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_intake_buffer_items_superseded_by_item_id", table_name="intake_buffer_items")
    op.drop_index("ix_intake_buffer_items_content_sha256", table_name="intake_buffer_items")
    op.drop_index("ix_intake_buffer_items_status", table_name="intake_buffer_items")
    op.drop_index("ix_intake_buffer_items_organization_id", table_name="intake_buffer_items")
    op.drop_index("ix_intake_buffer_items_workspace_id", table_name="intake_buffer_items")
    op.drop_table("intake_buffer_items")
