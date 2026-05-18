"""drop field_employees.supermemory_user_id

Revision ID: 0009_drop_supermemory_user_id
Revises: 0008_call_artifacts
Create Date: 2026-05-17

The column was the legacy way to identify a caller's Supermemory namespace
(value: "workspace:{wid}:caller:{eid}"). Supermemory's actual per-user
isolation is via `containerTags` (a list), not a single user_id - so we
derive the tags at write/search time from (workspace_id, field_employee_id)
on the row itself. No need to store anything.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_drop_supermemory_user_id"
down_revision: str | None = "0008_call_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("field_employees", "supermemory_user_id")


def downgrade() -> None:
    op.add_column(
        "field_employees",
        sa.Column("supermemory_user_id", sa.String(length=128), nullable=True),
    )
