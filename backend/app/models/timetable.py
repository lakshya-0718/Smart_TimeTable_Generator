"""
Timetable, TimetableEntry, and ConflictReport models.

Three models live in this file because they form an inseparable unit:
a Timetable header owns its entries and its conflict report.

──────────────────────────────────────────────────────────────────────
Timetable
──────────────────────────────────────────────────────────────────────
Header record for one generated timetable.
Status is ACTIVE (current) or SNAPSHOT (previous, one rollback point).
At most 2 timetables exist per semester at any time.

The partial unique index enforces "exactly one ACTIVE per semester" at
the DB level, not just the service layer.  This index is created via a
DDL event listener rather than __table_args__ because SQLAlchemy 2.0
doesn't support partial unique indexes through UniqueConstraint directly.
The migration will create it as a raw SQL index.

──────────────────────────────────────────────────────────────────────
TimetableEntry
──────────────────────────────────────────────────────────────────────
One row per successfully scheduled session (lecture, tutorial, or lab).
This is the most-queried table: every grid render and every CSV export
reads from it.

Denormalised columns (section_id, faculty_id, ta_id):
  These are copied from CourseAssignment at INSERT time.  They eliminate
  a JOIN through course_assignments on every filtered read ("all sessions
  for section Y2A", "all sessions for Dr. Sharma").  Since entries are
  immutable after generation, denormalisation carries zero update-anomaly
  risk.

Four unique constraints guard the four independent resources:
  room × (timetable, day, start_slot)     — no room double-booking
  section × (timetable, day, start_slot)  — no section clash
  faculty × (timetable, day, start_slot)  — no faculty clash
  ta × (timetable, day, start_slot)       — no TA clash (partial: ta_id IS NOT NULL)

The TA partial unique constraint is implemented as a DB-level partial
index in the Alembic migration (SQLAlchemy UniqueConstraint cannot
express a WHERE clause).  The three non-partial constraints are
expressed here as UniqueConstraint objects.

`start_slot` and `end_slot` are integers (8–18):
  8  = 8:00–9:00, 9 = 9:00–10:00, ..., 17 = 17:00–18:00
  For a 1-slot session: end_slot = start_slot + 1
  For a 3-slot lab: end_slot = start_slot + 3
  Storing end_slot avoids arithmetic on every slot-range query.

──────────────────────────────────────────────────────────────────────
ConflictReport
──────────────────────────────────────────────────────────────────────
1:1 with Timetable.  Stores the JSONB array output of conflict.py for
sessions the scheduler could not place.

JSONB is used here (and only here) because:
  - The report is always read as a complete unit (never filtered by column)
  - `blocking_constraints` is a variable-length list (awkward to normalise)
  - Adding new reason_codes requires no schema migration
"""

import uuid

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPKCreatedAtMixin, UUIDPrimaryKeyMixin
from app.models.enums import DayOfWeek, SessionType, TimetableStatus


class Timetable(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "timetables"

    # ── Core fields ──────────────────────────────────────────────────
    semester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("semesters.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[TimetableStatus] = mapped_column(
        Enum(TimetableStatus, name="timetable_status", create_constraint=True),
        nullable=False,
    )
    # Timestamp set at generation time (may differ slightly from created_at
    # if there is service-layer latency; stored explicitly for display)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # ── Relationships ─────────────────────────────────────────────────
    # Admin who triggered the generation (nullable: SET NULL if user deleted)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Constraints & indexes ─────────────────────────────────────────
    # NOTE: The partial unique index
    #   CREATE UNIQUE INDEX ON timetables (semester_id) WHERE status = 'ACTIVE'
    # cannot be expressed via UniqueConstraint (no WHERE clause support).
    # It is created as a raw DDL statement in the Alembic migration.
    __table_args__ = (
        Index("idx_timetables_semester_id", "semester_id"),
        Index("idx_timetables_status", "status"),
        # Composite: "give me the ACTIVE timetable for semester X" — hot path
        Index("idx_timetables_semester_status", "semester_id", "status"),
    )

    semester: Mapped["Semester"] = relationship(
        "Semester",
        back_populates="timetables",
    )
    generator: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[generated_by],
        back_populates="generated_timetables",
    )
    entries: Mapped[list["TimetableEntry"]] = relationship(
        "TimetableEntry",
        back_populates="timetable",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    conflict_report: Mapped["ConflictReport | None"] = relationship(
        "ConflictReport",
        back_populates="timetable",
        cascade="all, delete-orphan",
        uselist=False,  # 1:1
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Timetable semester={self.semester_id} [{self.status.value}]>"


class TimetableEntry(UUIDPKCreatedAtMixin, Base):
    __tablename__ = "timetable_entries"

    # ── Foreign keys ──────────────────────────────────────────────────
    timetable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("timetables.id", ondelete="CASCADE"),
        nullable=False,
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("course_assignments.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ── Scheduling fields ─────────────────────────────────────────────
    session_type: Mapped[SessionType] = mapped_column(
        Enum(SessionType, name="session_type", create_constraint=True),
        nullable=False,
    )
    day: Mapped[DayOfWeek] = mapped_column(
        # Reuse the day_of_week ENUM already created by FacultyAvailability
        Enum(DayOfWeek, name="day_of_week", create_constraint=False),
        nullable=False,
    )
    # Integer hour of session start: 8–17
    start_slot: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    # Integer hour of session end: 9–18 (always > start_slot)
    end_slot: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )

    # ── Resource foreign keys ─────────────────────────────────────────
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rooms.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # ── Denormalised fields (copied from CourseAssignment at INSERT) ───
    # Eliminates JOIN through course_assignments on every grid/CSV read.
    # Safe because entries are immutable after generation.
    section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    faculty_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Null for LECTURE and LAB sessions (only TUTORIAL sessions have a TA)
    ta_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Constraints & indexes ─────────────────────────────────────────
    __table_args__ = (
        # Domain constraints
        CheckConstraint(
            "start_slot BETWEEN 8 AND 17",
            name="ck_te_start_slot_range",
        ),
        CheckConstraint(
            "end_slot BETWEEN 9 AND 18",
            name="ck_te_end_slot_range",
        ),
        CheckConstraint(
            "end_slot > start_slot",
            name="ck_te_end_after_start",
        ),

        # ── Four resource-clash unique constraints ──────────────────
        # Each guards a distinct resource.  They are the DB-level backstop
        # mirroring the four clash checks in validator.py.

        # 1. No room double-booking within a timetable
        UniqueConstraint(
            "timetable_id", "room_id", "day", "start_slot",
            name="uq_te_room_day_slot",
        ),
        # 2. No section clash within a timetable
        UniqueConstraint(
            "timetable_id", "section_id", "day", "start_slot",
            name="uq_te_section_day_slot",
        ),
        # 3. No faculty clash within a timetable
        UniqueConstraint(
            "timetable_id", "faculty_id", "day", "start_slot",
            name="uq_te_faculty_day_slot",
        ),
        # 4. No TA clash within a timetable (partial: WHERE ta_id IS NOT NULL)
        # CANNOT be expressed here — no WHERE clause support in UniqueConstraint.
        # Created as raw DDL in the Alembic migration:
        #   CREATE UNIQUE INDEX uq_te_ta_day_slot
        #     ON timetable_entries (timetable_id, ta_id, day, start_slot)
        #     WHERE ta_id IS NOT NULL;

        # ── Read-path indexes ───────────────────────────────────────
        # Load all entries for a timetable (Timetable Viewer initial load)
        Index("idx_te_timetable_id", "timetable_id"),
        # Section timetable view / CSV export
        Index("idx_te_section_day", "timetable_id", "section_id", "day"),
        # Faculty timetable view / CSV export
        Index("idx_te_faculty_day", "timetable_id", "faculty_id", "day"),
        # Room timetable view / CSV export
        Index("idx_te_room_day", "timetable_id", "room_id", "day"),
        # TA timetable view
        Index("idx_te_ta_id", "timetable_id", "ta_id"),
        # Lookup all scheduled sessions for a given assignment
        Index("idx_te_assignment_id", "assignment_id"),
    )

    # ── Relationships ─────────────────────────────────────────────────
    timetable: Mapped["Timetable"] = relationship(
        "Timetable",
        back_populates="entries",
    )
    assignment: Mapped["CourseAssignment"] = relationship(
        "CourseAssignment",
        back_populates="timetable_entries",
    )
    room: Mapped["Room"] = relationship(
        "Room",
        back_populates="timetable_entries",
    )
    section: Mapped["Section"] = relationship(
        "Section",
        back_populates="timetable_entries",
    )
    faculty: Mapped["User"] = relationship(
        "User",
        foreign_keys=[faculty_id],
        back_populates="faculty_entries",
    )
    ta: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[ta_id],
        back_populates="ta_entries",
    )

    def __repr__(self) -> str:
        return (
            f"<TimetableEntry {self.session_type.value} "
            f"{self.day.value} {self.start_slot}–{self.end_slot} "
            f"room={self.room_id}>"
        )


class ConflictReport(UUIDPKCreatedAtMixin, Base):
    """
    1:1 with Timetable.  Stores the JSONB output of the scheduler's
    conflict.py module — the list of sessions that could not be placed.

    JSONB structure of `report`:
    [
      {
        "assignment_id":       "uuid",
        "course_code":         "CS301",
        "course_name":         "Data Structures",
        "section":             "Y2A",
        "session_type":        "LAB",
        "reason_code":         "NO_VALID_ROOM",
        "reason_detail":       "No LAB room with capacity >= 65 ...",
        "blocking_constraints": ["ROOM_CAPACITY", "LAB_CONSECUTIVE"]
      },
      ...
    ]

    An empty report `[]` means the scheduler placed every session
    successfully (conflict-free timetable).
    """

    __tablename__ = "conflict_reports"

    timetable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("timetables.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # enforces 1:1 with timetable
    )
    # Array of conflict item objects — always read as a unit, never
    # filtered by individual field.  Defaults to an empty JSON array
    # (represents a fully successful timetable generation).
    report: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default="'[]'::jsonb",
    )

    # ── Constraints & indexes ─────────────────────────────────────────
    __table_args__ = (
        # Fast lookup: "get the conflict report for timetable X"
        Index("idx_cr_timetable_id", "timetable_id"),
        # GIN index for JSONB path queries (optional analytics)
        # e.g. WHERE report @> '[{"reason_code": "NO_ROOM"}]'
        Index("idx_cr_report_gin", "report", postgresql_using="gin"),
    )

    # ── Relationships ─────────────────────────────────────────────────
    timetable: Mapped["Timetable"] = relationship(
        "Timetable",
        back_populates="conflict_report",
    )

    def __repr__(self) -> str:
        count = len(self.report) if self.report else 0
        return f"<ConflictReport timetable={self.timetable_id} items={count}>"
