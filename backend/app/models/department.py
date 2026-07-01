"""
Department model — the organizational unit that owns timetables.

A department has faculty, sections, and courses. Timetables are
generated per-department so that cross-department conflicts are
handled at a higher coordination layer (out of scope for v1).
"""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin


class Department(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "departments"

    name: Mapped[str] = mapped_column(
        String(150), unique=True, nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(
        String(10), unique=True, nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Relationships ────────────────────────────────────────────────
    faculty_members = relationship(
        "Faculty", back_populates="department", lazy="selectin"
    )
    sections = relationship(
        "Section", back_populates="department", lazy="selectin"
    )
    courses = relationship(
        "Course", back_populates="department", lazy="selectin"
    )
    timetables = relationship(
        "Timetable", back_populates="department", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Department {self.code}>"
