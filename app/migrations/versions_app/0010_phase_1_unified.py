"""phase 1 unified migration

Revision ID: 0010_phase_1_unified
Revises: 0009_drop_supermemory_user_id
Create Date: 2026-05-17

Single migration covering all of Phase 1 (Durability + Productivity) — see
`lld/phase_1_durability_and_productivity.md`. Consolidated per the LLD's
optimization summary so there's one foundation step before Wave B.

Adds / extends:
  - call_artifacts.kind CHECK widening (action_item_handler_outcome, daily_brief)
  - intake_buffer_items.source CHECK widening (rep_email_followup)
  - decision_requests.status CHECK widening (answered_late, F8 resolve_now CTA)
  - manager_workspaces: email_inbox_id, email_inbox_addr, email_domain
  - new tables: action_items, manager_interventions, claim_verifications,
    email_messages, workspace_oauth_credentials, dashboard_snapshots,
    saved_dashboard_queries, correction_intakes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_phase_1_unified"
down_revision: str | None = "0009_drop_supermemory_user_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- 1. Widen call_artifacts.kind CHECK (F1 + F3 + F8) ----
    op.drop_constraint("kind", "call_artifacts", type_="check")
    op.create_check_constraint(
        "kind",
        "call_artifacts",
        "kind IN ('canonical_summary','transcript','recording','provider_summary',"
        "'action_items_export','action_item_handler_outcome','daily_brief')",
    )

    # ---- 2. Widen intake_buffer_items.source CHECK (F6) ----
    op.drop_constraint("source", "intake_buffer_items", type_="check")
    op.create_check_constraint(
        "source",
        "intake_buffer_items",
        "source IN ('form', 'upload', 'voice_intake', 'correction', 'rep_email_followup')",
    )

    # ---- 2b. Widen decision_requests.status CHECK (F8 resolve_now) ----
    op.drop_constraint("status", "decision_requests", type_="check")
    op.create_check_constraint(
        "status",
        "decision_requests",
        "status IN ('open','answered','answered_late','timed_out','cancelled')",
    )

    # ---- 3. ManagerWorkspace email columns (F6) ----
    op.add_column("manager_workspaces", sa.Column("email_inbox_id", sa.String(length=64), nullable=True))
    op.add_column(
        "manager_workspaces", sa.Column("email_inbox_addr", sa.String(length=320), nullable=True)
    )
    op.add_column("manager_workspaces", sa.Column("email_domain", sa.String(length=255), nullable=True))

    # ---- 4. correction_intakes (NEW — assumed-existing per LLD; we create it now) ----
    op.create_table(
        "correction_intakes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("source_ref_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'open'")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["manager_workspaces.id"], ondelete="CASCADE",
            name="fk_correction_intakes_workspace_id_manager_workspaces",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT",
            name="fk_correction_intakes_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"], ["users.id"], ondelete="RESTRICT",
            name="fk_correction_intakes_target_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT",
            name="fk_correction_intakes_reviewed_by_user_id_users",
        ),
        sa.CheckConstraint(
            "origin IN ('manager','rep_callback','system_web_verifier','manager_email_reply')",
            name="ck_correction_intakes_origin",
        ),
        sa.CheckConstraint(
            "status IN ('open','applied','rejected','dismissed')",
            name="ck_correction_intakes_status",
        ),
    )
    op.create_index("ix_correction_intakes_workspace_id", "correction_intakes", ["workspace_id"])
    op.create_index("ix_correction_intakes_organization_id", "correction_intakes", ["organization_id"])
    op.create_index("ix_correction_intakes_origin", "correction_intakes", ["origin"])
    op.create_index("ix_correction_intakes_status", "correction_intakes", ["status"])

    # ---- 5. action_items (F3) ----
    op.create_table(
        "action_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'pending_approval'"),
        ),
        sa.Column("extracted_by", sa.String(length=128), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("handler", sa.String(length=32), nullable=False, server_default=sa.text("'none'")),
        sa.Column("handler_outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("handler_outcome_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("handler_executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handler_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("handler_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["manager_workspaces.id"], ondelete="CASCADE",
            name="fk_action_items_workspace_id_manager_workspaces",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT",
            name="fk_action_items_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["call_id"], ["calls.id"], ondelete="SET NULL",
            name="fk_action_items_call_id_calls",
        ),
        sa.ForeignKeyConstraint(
            ["handler_outcome_artifact_id"], ["call_artifacts.id"], ondelete="SET NULL",
            name="fk_action_items_handler_outcome_artifact_id_call_artifacts",
        ),
        sa.CheckConstraint(
            "status IN ('pending_approval','needs_review','approved','done',"
            "'failed','needs_reconnect','rejected')",
            name="ck_action_items_status",
        ),
        sa.CheckConstraint(
            "handler IN ('scheduler','email_drafter','none')",
            name="ck_action_items_handler",
        ),
    )
    op.create_index("ix_action_items_workspace_id", "action_items", ["workspace_id"])
    op.create_index("ix_action_items_organization_id", "action_items", ["organization_id"])
    op.create_index("ix_action_items_call_id", "action_items", ["call_id"])
    op.create_index("ix_action_items_status", "action_items", ["status"])

    # ---- 6. manager_interventions (F7) ----
    op.create_table(
        "manager_interventions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["call_id"], ["calls.id"], ondelete="CASCADE",
            name="fk_manager_interventions_call_id_calls",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["manager_workspaces.id"], ondelete="CASCADE",
            name="fk_manager_interventions_workspace_id_manager_workspaces",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="RESTRICT",
            name="fk_manager_interventions_user_id_users",
        ),
        sa.CheckConstraint("mode IN ('whisper')", name="ck_manager_interventions_mode"),
    )
    op.create_index("ix_manager_interventions_call_id", "manager_interventions", ["call_id"])
    op.create_index("ix_manager_interventions_workspace_id", "manager_interventions", ["workspace_id"])

    # ---- 7. claim_verifications (F5) ----
    op.create_table(
        "claim_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_subject", sa.String(length=256), nullable=False),
        sa.Column("claim_predicate", sa.String(length=128), nullable=False),
        sa.Column("claim_object", sa.String(length=512), nullable=False),
        sa.Column("claim_source_utterance", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_url", sa.String(length=2048), nullable=True),
        sa.Column("evidence_snippet", sa.Text(), nullable=True),
        sa.Column("contradiction_detail", sa.Text(), nullable=True),
        sa.Column("correction_intake_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["manager_workspaces.id"], ondelete="CASCADE",
            name="fk_claim_verifications_workspace_id_manager_workspaces",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT",
            name="fk_claim_verifications_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["call_id"], ["calls.id"], ondelete="CASCADE",
            name="fk_claim_verifications_call_id_calls",
        ),
        sa.ForeignKeyConstraint(
            ["correction_intake_id"], ["correction_intakes.id"], ondelete="SET NULL",
            name="fk_claim_verifications_correction_intake_id_correction_intakes",
        ),
        sa.CheckConstraint(
            "status IN ('corroborated','unconfirmed','contradicted')",
            name="ck_claim_verifications_status",
        ),
    )
    op.create_index("ix_claim_verifications_workspace_id", "claim_verifications", ["workspace_id"])
    op.create_index("ix_claim_verifications_organization_id", "claim_verifications", ["organization_id"])
    op.create_index("ix_claim_verifications_call_id", "claim_verifications", ["call_id"])
    op.create_index("ix_claim_verifications_claim_subject", "claim_verifications", ["claim_subject"])
    op.create_index("ix_claim_verifications_status", "claim_verifications", ["status"])
    op.create_index(
        "ix_claim_verifications_workspace_call", "claim_verifications", ["workspace_id", "call_id"]
    )

    # ---- 8. email_messages (F6) ----
    op.create_table(
        "email_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_message_id", sa.String(length=256), nullable=False),
        sa.Column("provider_thread_id", sa.String(length=256), nullable=False),
        sa.Column("trigger_kind", sa.String(length=64), nullable=False),
        sa.Column("trigger_ref_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_class", sa.String(length=32), nullable=False),
        sa.Column("recipient_addr", sa.String(length=320), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["manager_workspaces.id"], ondelete="CASCADE",
            name="fk_email_messages_workspace_id_manager_workspaces",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT",
            name="fk_email_messages_organization_id_organizations",
        ),
        sa.UniqueConstraint(
            "correlation_idempotency_key",
            name="uq_email_messages_correlation_idempotency_key",
        ),
        sa.CheckConstraint(
            "provider IN ('agentmail','oauth_personal')",
            name="ck_email_messages_provider",
        ),
        sa.CheckConstraint(
            "trigger_kind IN ('post_call_summary','daily_brief','missed_decisions',"
            "'action_item_handler')",
            name="ck_email_messages_trigger_kind",
        ),
        sa.CheckConstraint(
            "recipient_class IN ('manager','rep','external_customer')",
            name="ck_email_messages_recipient_class",
        ),
    )
    op.create_index("ix_email_messages_workspace_id", "email_messages", ["workspace_id"])
    op.create_index("ix_email_messages_provider_message_id", "email_messages", ["provider_message_id"])
    op.create_index("ix_email_messages_provider_thread_id", "email_messages", ["provider_thread_id"])

    # ---- 9. workspace_oauth_credentials (F9) ----
    op.create_table(
        "workspace_oauth_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["manager_workspaces.id"], ondelete="CASCADE",
            name="fk_workspace_oauth_credentials_workspace_id_manager_workspaces",
        ),
        sa.ForeignKeyConstraint(
            ["connected_by_user_id"], ["users.id"], ondelete="RESTRICT",
            name="fk_workspace_oauth_credentials_connected_by_user_id_users",
        ),
        sa.CheckConstraint(
            "provider IN ('google_workspace')",
            name="ck_workspace_oauth_credentials_provider",
        ),
    )
    op.create_index(
        "ix_workspace_oauth_credentials_workspace_id",
        "workspace_oauth_credentials", ["workspace_id"],
    )
    op.create_index(
        "ix_workspace_oauth_credentials_provider",
        "workspace_oauth_credentials", ["provider"],
    )

    # ---- 10. dashboard_snapshots (F8) ----
    op.create_table(
        "dashboard_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=256), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["manager_workspaces.id"], ondelete="CASCADE",
            name="fk_dashboard_snapshots_workspace_id_manager_workspaces",
        ),
        sa.CheckConstraint(
            "dimension IN ('overview','rep','account','theme','decision')",
            name="ck_dashboard_snapshots_dimension",
        ),
    )
    op.create_index("ix_dashboard_snapshots_dimension", "dashboard_snapshots", ["dimension"])
    op.create_index(
        "ix_dashboard_snapshots_ws_date_dim",
        "dashboard_snapshots", ["workspace_id", "snapshot_date", "dimension"],
    )

    # ---- 11. saved_dashboard_queries (F8) ----
    op.create_table(
        "saved_dashboard_queries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["manager_workspaces.id"], ondelete="CASCADE",
            name="fk_saved_dashboard_queries_workspace_id_manager_workspaces",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="RESTRICT",
            name="fk_saved_dashboard_queries_user_id_users",
        ),
    )
    op.create_index(
        "ix_saved_dashboard_queries_workspace_id",
        "saved_dashboard_queries", ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_saved_dashboard_queries_workspace_id", table_name="saved_dashboard_queries")
    op.drop_table("saved_dashboard_queries")

    op.drop_index("ix_dashboard_snapshots_ws_date_dim", table_name="dashboard_snapshots")
    op.drop_index("ix_dashboard_snapshots_dimension", table_name="dashboard_snapshots")
    op.drop_table("dashboard_snapshots")

    op.drop_index(
        "ix_workspace_oauth_credentials_provider", table_name="workspace_oauth_credentials"
    )
    op.drop_index(
        "ix_workspace_oauth_credentials_workspace_id", table_name="workspace_oauth_credentials"
    )
    op.drop_table("workspace_oauth_credentials")

    op.drop_index("ix_email_messages_provider_thread_id", table_name="email_messages")
    op.drop_index("ix_email_messages_provider_message_id", table_name="email_messages")
    op.drop_index("ix_email_messages_workspace_id", table_name="email_messages")
    op.drop_table("email_messages")

    op.drop_index("ix_claim_verifications_workspace_call", table_name="claim_verifications")
    op.drop_index("ix_claim_verifications_status", table_name="claim_verifications")
    op.drop_index("ix_claim_verifications_claim_subject", table_name="claim_verifications")
    op.drop_index("ix_claim_verifications_call_id", table_name="claim_verifications")
    op.drop_index("ix_claim_verifications_organization_id", table_name="claim_verifications")
    op.drop_index("ix_claim_verifications_workspace_id", table_name="claim_verifications")
    op.drop_table("claim_verifications")

    op.drop_index("ix_manager_interventions_workspace_id", table_name="manager_interventions")
    op.drop_index("ix_manager_interventions_call_id", table_name="manager_interventions")
    op.drop_table("manager_interventions")

    op.drop_index("ix_action_items_status", table_name="action_items")
    op.drop_index("ix_action_items_call_id", table_name="action_items")
    op.drop_index("ix_action_items_organization_id", table_name="action_items")
    op.drop_index("ix_action_items_workspace_id", table_name="action_items")
    op.drop_table("action_items")

    op.drop_index("ix_correction_intakes_status", table_name="correction_intakes")
    op.drop_index("ix_correction_intakes_origin", table_name="correction_intakes")
    op.drop_index("ix_correction_intakes_organization_id", table_name="correction_intakes")
    op.drop_index("ix_correction_intakes_workspace_id", table_name="correction_intakes")
    op.drop_table("correction_intakes")

    op.drop_column("manager_workspaces", "email_domain")
    op.drop_column("manager_workspaces", "email_inbox_addr")
    op.drop_column("manager_workspaces", "email_inbox_id")

    op.drop_constraint("source", "intake_buffer_items", type_="check")
    op.create_check_constraint(
        "source",
        "intake_buffer_items",
        "source IN ('form', 'upload', 'voice_intake', 'correction')",
    )

    op.drop_constraint("status", "decision_requests", type_="check")
    op.create_check_constraint(
        "status",
        "decision_requests",
        "status IN ('open','answered','timed_out','cancelled')",
    )

    op.drop_constraint("kind", "call_artifacts", type_="check")
    op.create_check_constraint(
        "kind",
        "call_artifacts",
        "kind IN ('canonical_summary','transcript','recording','provider_summary','action_items_export')",
    )
