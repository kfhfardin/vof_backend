"""Organization — top-level container.

Phase 0: auto-created at Manager signup, single-Manager per org, invisible
in the UI. The row exists so future multi-Manager Organizations can be
lit up without schema changes (HLD §2, §5.2).
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKey


class Organization(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
