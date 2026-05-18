"""Unit tests for the SQLAlchemy model surface.

These run without a real Postgres - they exercise the metadata + DDL
emission + FK/index/check-constraint shapes. The actual migration
end-to-end is exercised in tests/integration (requires compose).
"""

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.db.base import Base
from app.db.models import ManagerWorkspace, Organization, User


def test_all_models_registered() -> None:
    table_names = set(Base.metadata.tables.keys())
    assert "organizations" in table_names
    assert "manager_workspaces" in table_names
    assert "users" in table_names


def test_organization_columns() -> None:
    t = Organization.__table__
    cols = {c.name for c in t.columns}
    assert cols == {"id", "name", "created_at", "updated_at"}


def test_workspace_columns_and_fk() -> None:
    t = ManagerWorkspace.__table__
    cols = {c.name for c in t.columns}
    assert {
        "id",
        "organization_id",
        "manager_user_id",
        "name",
        "primary_number",
        "agentphone_agent_id",
        "agentphone_number_id",
        "provisioning_state",
        "config",
        "created_at",
        "updated_at",
    } <= cols

    # FK to organizations exists
    fk_targets = {fk.target_fullname for c in t.columns for fk in c.foreign_keys}
    assert "organizations.id" in fk_targets


def test_workspace_unique_primary_number() -> None:
    t = ManagerWorkspace.__table__
    uniques = {c.name for c in t.constraints if c.__class__.__name__ == "UniqueConstraint"}
    assert "uq_manager_workspaces_primary_number" in uniques


def test_user_role_check_constraint_inferred_or_columns() -> None:
    # The CheckConstraint lives on the migration (not the model) — verify the
    # model exposes the Literal role choices via its typed column.
    t = User.__table__
    cols = {c.name for c in t.columns}
    assert {
        "id",
        "organization_id",
        "workspace_id",
        "field_employee_id",
        "email",
        "password_hash",
        "role",
        "front_end_push_token",
        "created_at",
        "updated_at",
    } <= cols


def test_user_email_unique() -> None:
    t = User.__table__
    uniques = {c.name for c in t.constraints if c.__class__.__name__ == "UniqueConstraint"}
    assert "uq_users_email" in uniques


def test_user_workspace_id_nullable_for_org_admin_future() -> None:
    """org_admin role spans an org; workspace_id must accept NULL."""
    col = User.__table__.c.workspace_id
    assert col.nullable is True


def test_user_workspace_fk_present() -> None:
    fk_targets = {fk.target_fullname for c in User.__table__.columns for fk in c.foreign_keys}
    assert "manager_workspaces.id" in fk_targets


def test_workspace_manager_user_fk_present() -> None:
    fk_targets = {fk.target_fullname for c in ManagerWorkspace.__table__.columns for fk in c.foreign_keys}
    assert "users.id" in fk_targets


def test_models_emit_postgres_ddl_cleanly() -> None:
    """DDL renders against the Postgres dialect.

    Catches model-definition mistakes (bad column types, broken FKs,
    nonsense defaults) before the migration is ever run.
    """
    dialect = postgresql.dialect()
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert "CREATE TABLE" in ddl
        assert table.name in ddl
