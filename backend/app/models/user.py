"""
User model — single table for all three actor roles.

Design decision: Admin, Faculty, and TA all authenticate via the same
mechanism (email + bcrypt password → JWT).  Splitting them into separate
tables would create three identical auth code paths and complicate
availability queries.  The `role` column is the single discriminator.

Relationships from User:
  - faculty_availability  (1:N, cascade delete)
  - ta_availability       (1:N, cascade delete)
  - course_assignments    as faculty (1:N, RESTRICT delete)
  - course_assignments    as TA      (1:N, SET NULL delete)
  - timetable_entries     as faculty (1:N, RESTRICT delete — denorm)
  - timetable_entries     as TA      (1:N, SET NULL delete — denorm)
  - timetables            as generator (1:N, SET NULL delete)
"""

import uuid

from sqlalchemy import Boolean, Enum, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin
from app.models.enums import UserRole


class User(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "users"

    # ── Core fields ──────────────────────────────────────────────────
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", create_constraint=True),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="true",
    )

    # ── Indexes ───────────────────────────────────────────────────────
    # idx_users_email  — used on every login lookup (hot path)
    # idx_users_role   — used when listing all faculty/TAs for dropdowns
    __table_args__ = (
        Index("idx_users_email", "email"),
        Index("idx_users_role", "role"),
    )

    # ── Relationships ─────────────────────────────────────────────────
    # Faculty unavailability slots (role=FACULTY enforced at service layer)
    faculty_availability: Mapped[list["FacultyAvailability"]] = relationship(
        "FacultyAvailability",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    # TA unavailability slots (role=TA enforced at service layer)
    ta_availability: Mapped[list["TAAvailability"]] = relationship(
        "TAAvailability",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    # Courses this user teaches as faculty
    faculty_assignments: Mapped[list["CourseAssignment"]] = relationship(
        "CourseAssignment",
        foreign_keys="CourseAssignment.faculty_id",
        back_populates="faculty",
        lazy="selectin",
    )
    # Courses this user tutors as TA
    ta_assignments: Mapped[list["CourseAssignment"]] = relationship(
        "CourseAssignment",
        foreign_keys="CourseAssignment.ta_id",
        back_populates="ta",
        lazy="selectin",
    )
    # Timetable entries where this user is the faculty (denormalized)
    faculty_entries: Mapped[list["TimetableEntry"]] = relationship(
        "TimetableEntry",
        foreign_keys="TimetableEntry.faculty_id",
        back_populates="faculty",
        lazy="selectin",
    )
    # Timetable entries where this user is the TA (denormalized)
    ta_entries: Mapped[list["TimetableEntry"]] = relationship(
        "TimetableEntry",
        foreign_keys="TimetableEntry.ta_id",
        back_populates="ta",
        lazy="selectin",
    )
    # Timetables this user generated (as admin)
    generated_timetables: Mapped[list["Timetable"]] = relationship(
        "Timetable",
        foreign_keys="Timetable.generated_by",
        back_populates="generator",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<User {self.email} [{self.role.value}]>"
