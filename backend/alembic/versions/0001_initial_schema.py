"""Initial schema — Smart Academic Timetable Generator

Creates:
  Enum types   : user_role, course_tier, room_type, session_type,
                 day_of_week, timetable_status
  Tables (11)  : users, semesters, sections, rooms, courses,
                 faculty_availability, ta_availability,
                 course_assignments, timetables, timetable_entries,
                 conflict_reports
  Indexes      : all performance and uniqueness indexes documented in
                 database_schema.md, including two partial unique indexes
                 that cannot be expressed via SQLAlchemy UniqueConstraint:
                   - uq_timetables_active_per_semester
                     (timetables WHERE status = 'ACTIVE')
                   - uq_te_ta_day_slot
                     (timetable_entries WHERE ta_id IS NOT NULL)
  Trigger      : set_updated_at() PL/pgSQL function + per-table triggers
                 that keep updated_at current for DB-level writes that
                 bypass SQLAlchemy's onupdate= hook.

Revision ID : 0001
Revises     : (none — this is the first migration)
Create Date : 2026-06-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Alembic revision identifiers
# ---------------------------------------------------------------------------
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # ════════════════════════════════════════════════════════════════════════
    # 1.  PostgreSQL ENUM types
    #
    # Create all six enum types before any table references them.
    # We call .create() with checkfirst=True so that re-running in offline
    # mode does not error if the type already exists.
    # ════════════════════════════════════════════════════════════════════════

    postgresql.ENUM(
        "ADMIN", "FACULTY", "TA",
        name="user_role",
        create_type=False,
    ).create(op.get_bind(), checkfirst=True)

    postgresql.ENUM(
        "TIER_1", "TIER_2", "TIER_3", "TIER_4",
        name="course_tier",
        create_type=False,
    ).create(op.get_bind(), checkfirst=True)

    postgresql.ENUM(
        "LECTURE_HALL", "LAB",
        name="room_type",
        create_type=False,
    ).create(op.get_bind(), checkfirst=True)

    postgresql.ENUM(
        "LECTURE", "TUTORIAL", "LAB",
        name="session_type",
        create_type=False,
    ).create(op.get_bind(), checkfirst=True)

    postgresql.ENUM(
        "MON", "TUE", "WED", "THU", "FRI",
        name="day_of_week",
        create_type=False,
    ).create(op.get_bind(), checkfirst=True)

    postgresql.ENUM(
        "ACTIVE", "SNAPSHOT",
        name="timetable_status",
        create_type=False,
    ).create(op.get_bind(), checkfirst=True)

    # ════════════════════════════════════════════════════════════════════════
    # 2.  set_updated_at() trigger function
    #
    # Shared PL/pgSQL function used by every mutable table.
    # Keeps `updated_at` current for writes that bypass SQLAlchemy's
    # Python-side onupdate= hook (raw psql, Alembic data migrations, etc.).
    # ════════════════════════════════════════════════════════════════════════

    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # ════════════════════════════════════════════════════════════════════════
    # 3.  TABLE: users
    #
    # Single table for all three actor roles (ADMIN, FACULTY, TA).
    # `role` is the only discriminator. Auth mechanism is identical for all.
    # ════════════════════════════════════════════════════════════════════════

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("email",           sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name",       sa.String(255), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("ADMIN", "FACULTY", "TA", name="user_role", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    # idx_users_email — hot path: every login lookup
    op.create_index("idx_users_email", "users", ["email"])
    # idx_users_role  — used when listing all faculty/TAs for dropdowns
    op.create_index("idx_users_role",  "users", ["role"])

    op.execute("""
        CREATE TRIGGER trg_users_updated_at
        BEFORE UPDATE ON users
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    # ════════════════════════════════════════════════════════════════════════
    # 4.  TABLE: semesters
    # ════════════════════════════════════════════════════════════════════════

    op.create_table(
        "semesters",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
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
        sa.UniqueConstraint("name", name="uq_semesters_name"),
    )

    # "Get the currently active semester" — used constantly
    op.create_index("idx_semesters_is_active", "semesters", ["is_active"])

    op.execute("""
        CREATE TRIGGER trg_semesters_updated_at
        BEFORE UPDATE ON semesters
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    # ════════════════════════════════════════════════════════════════════════
    # 5.  TABLE: sections
    #
    # Permanent student groups (Y1A–Y4B). Not semester-scoped.
    # `year` and `label` are separate columns to allow integer filtering
    # without string parsing (e.g. "show all Year 2 timetables").
    # ════════════════════════════════════════════════════════════════════════

    op.create_table(
        "sections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("name",     sa.String(10),   nullable=False),
        sa.Column("year",     sa.SmallInteger, nullable=False),
        sa.Column("label",    sa.CHAR(1),      nullable=False),
        sa.Column("strength", sa.SmallInteger, nullable=False),
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
        # "Y2A" cannot appear twice
        sa.UniqueConstraint("name", name="uq_sections_name"),
        # At most one section per (year, label) combination
        sa.UniqueConstraint("year", "label", name="uq_sections_year_label"),
        sa.CheckConstraint("year BETWEEN 1 AND 4", name="ck_sections_year_range"),
        sa.CheckConstraint("label IN ('A', 'B')",  name="ck_sections_label_values"),
        sa.CheckConstraint("strength > 0",          name="ck_sections_strength_positive"),
    )

    # Used in virtually every JOIN path
    op.create_index("idx_sections_name", "sections", ["name"])
    # Used for year-level timetable views
    op.create_index("idx_sections_year", "sections", ["year"])

    op.execute("""
        CREATE TRIGGER trg_sections_updated_at
        BEFORE UPDATE ON sections
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    # ════════════════════════════════════════════════════════════════════════
    # 6.  TABLE: rooms
    # ════════════════════════════════════════════════════════════════════════

    op.create_table(
        "rooms",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "room_type",
            postgresql.ENUM("LECTURE_HALL", "LAB", name="room_type", create_type=False),
            nullable=False,
        ),
        sa.Column("capacity", sa.SmallInteger, nullable=False),
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
        sa.UniqueConstraint("name", name="uq_rooms_name"),
        sa.CheckConstraint("capacity > 0", name="ck_rooms_capacity_positive"),
    )

    # Scheduler best-fit query: WHERE room_type = :t ORDER BY capacity ASC
    op.create_index("idx_rooms_type_capacity", "rooms", ["room_type", "capacity"])

    op.execute("""
        CREATE TRIGGER trg_rooms_updated_at
        BEFORE UPDATE ON rooms
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    # ════════════════════════════════════════════════════════════════════════
    # 7.  TABLE: courses
    #
    # Semester-scoped. `tier` encodes the full L-T-P pattern as a single
    # enum value. FK to semesters: ON DELETE CASCADE.
    # ════════════════════════════════════════════════════════════════════════

    op.create_table(
        "courses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "semester_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("semesters.id", ondelete="CASCADE", name="fk_courses_semester_id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(20),  nullable=False),
        sa.Column(
            "tier",
            postgresql.ENUM("TIER_1", "TIER_2", "TIER_3", "TIER_4", name="course_tier", create_type=False),
            nullable=False,
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
        # Same course code cannot appear twice in the same semester
        sa.UniqueConstraint("semester_id", "code", name="uq_courses_semester_code"),
    )

    # Hot path: load all courses for a semester (every scheduler run)
    op.create_index("idx_courses_semester_id", "courses", ["semester_id"])
    # Sort courses by scheduling priority (TIER_1 first)
    op.create_index("idx_courses_tier",        "courses", ["tier"])

    op.execute("""
        CREATE TRIGGER trg_courses_updated_at
        BEFORE UPDATE ON courses
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    # ════════════════════════════════════════════════════════════════════════
    # 8.  TABLE: faculty_availability
    #
    # Each row = one (faculty, day, hour) blacklist slot.
    # No updated_at — rows use replace semantics (delete-then-insert).
    # ════════════════════════════════════════════════════════════════════════

    op.create_table(
        "faculty_availability",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_faculty_availability_user_id"),
            nullable=False,
        ),
        sa.Column(
            "day",
            postgresql.ENUM("MON", "TUE", "WED", "THU", "FRI", name="day_of_week", create_type=False),
            nullable=False,
        ),
        # 8 = 8:00–9:00 … 17 = 17:00–18:00
        sa.Column("slot_hour", sa.SmallInteger, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Prevents double-marking; also serves as hot-path scheduler index
        sa.UniqueConstraint(
            "user_id", "day", "slot_hour",
            name="uq_faculty_avail_user_day_slot",
        ),
        sa.CheckConstraint("slot_hour BETWEEN 8 AND 17", name="ck_faculty_avail_slot_hour_range"),
    )

    # "Load all unavailable slots for faculty X"
    op.create_index("idx_faculty_avail_user_id", "faculty_availability", ["user_id"])
    # O(1) validator lookup: (user_id, day, slot_hour) — hot path in scheduler
    op.create_index(
        "idx_faculty_avail_lookup",
        "faculty_availability",
        ["user_id", "day", "slot_hour"],
    )

    # ════════════════════════════════════════════════════════════════════════
    # 9.  TABLE: ta_availability
    #
    # Structurally identical to faculty_availability but kept separate for:
    #   - Independent index cardinality (never queried together with faculty)
    #   - Role clarity at the service layer
    #   - Future flexibility (TA daily cap = 3h vs faculty's 4h)
    # ════════════════════════════════════════════════════════════════════════

    op.create_table(
        "ta_availability",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_ta_availability_user_id"),
            nullable=False,
        ),
        sa.Column(
            "day",
            postgresql.ENUM("MON", "TUE", "WED", "THU", "FRI", name="day_of_week", create_type=False),
            nullable=False,
        ),
        sa.Column("slot_hour", sa.SmallInteger, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "day", "slot_hour", name="uq_ta_avail_user_day_slot"),
        sa.CheckConstraint("slot_hour BETWEEN 8 AND 17", name="ck_ta_avail_slot_hour_range"),
    )

    op.create_index("idx_ta_avail_user_id", "ta_availability", ["user_id"])
    op.create_index("idx_ta_avail_lookup",  "ta_availability", ["user_id", "day", "slot_hour"])

    # ════════════════════════════════════════════════════════════════════════
    # 10. TABLE: course_assignments
    #
    # Central scheduling atom: Course × Section × Faculty (× optional TA).
    # The engine expands each row into individual Session objects per tier.
    #
    # FK delete rules:
    #   course_id  → CASCADE   (semester cascade flows through here)
    #   section_id → RESTRICT  (can't remove a section with live assignments)
    #   faculty_id → RESTRICT  (can't remove a faculty with live assignments)
    #   ta_id      → SET NULL  (TA can be removed; assignment becomes TA-less)
    # ════════════════════════════════════════════════════════════════════════

    op.create_table(
        "course_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id",   ondelete="CASCADE",  name="fk_ca_course_id"),
            nullable=False,
        ),
        sa.Column(
            "section_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sections.id",  ondelete="RESTRICT", name="fk_ca_section_id"),
            nullable=False,
        ),
        sa.Column(
            "faculty_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id",     ondelete="RESTRICT", name="fk_ca_faculty_id"),
            nullable=False,
        ),
        # Nullable: lab-only tiers (TIER_3, TIER_4) have no tutorial and no TA
        sa.Column(
            "ta_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id",     ondelete="SET NULL", name="fk_ca_ta_id"),
            nullable=True,
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
        # A course may be assigned to a section at most once per semester
        sa.UniqueConstraint(
            "course_id", "section_id",
            name="uq_course_assignments_course_section",
        ),
    )

    op.create_index("idx_ca_course_id",  "course_assignments", ["course_id"])
    op.create_index("idx_ca_section_id", "course_assignments", ["section_id"])
    # "Show all courses assigned to this faculty member"
    op.create_index("idx_ca_faculty_id", "course_assignments", ["faculty_id"])
    # "Show all tutorial assignments for this TA"
    op.create_index("idx_ca_ta_id",      "course_assignments", ["ta_id"])

    op.execute("""
        CREATE TRIGGER trg_course_assignments_updated_at
        BEFORE UPDATE ON course_assignments
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    # ════════════════════════════════════════════════════════════════════════
    # 11. TABLE: timetables
    #
    # Header record for a generated timetable. At most 2 per semester:
    # one ACTIVE (current) and one SNAPSHOT (one rollback point).
    #
    # PARTIAL UNIQUE INDEX: uq_timetables_active_per_semester
    # ─────────────────────────────────────────────────────────
    # Enforces "at most one ACTIVE timetable per semester" at the DB level.
    # A full UniqueConstraint on (semester_id, status) would incorrectly
    # prevent two SNAPSHOT rows (semantically wrong even if not needed).
    # The WHERE clause restricts enforcement to ACTIVE rows only.
    # This CANNOT be expressed via SQLAlchemy UniqueConstraint — no WHERE
    # support. Created as raw DDL via op.execute() below.
    # ════════════════════════════════════════════════════════════════════════

    op.create_table(
        "timetables",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "semester_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("semesters.id", ondelete="CASCADE", name="fk_timetables_semester_id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM("ACTIVE", "SNAPSHOT", name="timetable_status", create_type=False),
            nullable=False,
        ),
        # Explicit generation timestamp — stored for display ("Generated by X on Y")
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Admin who triggered generation; SET NULL if that admin is deleted
        sa.Column(
            "generated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_timetables_generated_by"),
            nullable=True,
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
    )

    op.create_index("idx_timetables_semester_id",     "timetables", ["semester_id"])
    op.create_index("idx_timetables_status",          "timetables", ["status"])
    # Hot path: "give me the ACTIVE timetable for semester X"
    op.create_index("idx_timetables_semester_status", "timetables", ["semester_id", "status"])

    # ── Partial unique index ─────────────────────────────────────────────
    # At most ONE ACTIVE timetable per semester.
    # SNAPSHOT rows are not constrained here (managed by service logic).
    op.execute("""
        CREATE UNIQUE INDEX uq_timetables_active_per_semester
            ON timetables (semester_id)
            WHERE status = 'ACTIVE';
    """)

    op.execute("""
        CREATE TRIGGER trg_timetables_updated_at
        BEFORE UPDATE ON timetables
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    # ════════════════════════════════════════════════════════════════════════
    # 12. TABLE: timetable_entries
    #
    # One row per successfully scheduled session.
    # Most-queried table — every grid render and CSV export reads from it.
    #
    # Denormalized columns (section_id, faculty_id, ta_id):
    #   Copied from CourseAssignment at INSERT time.
    #   Eliminates a JOIN through course_assignments on every filtered read.
    #   Zero update-anomaly risk: entries are immutable after generation.
    #
    # Four unique constraints guard four independent resources:
    #   1. room    × (timetable_id, day, start_slot) — no room double-booking
    #   2. section × (timetable_id, day, start_slot) — no section clash
    #   3. faculty × (timetable_id, day, start_slot) — no faculty clash
    #   4. ta      × (timetable_id, day, start_slot) WHERE ta_id IS NOT NULL
    #      → Constraint 4 is a PARTIAL unique index (raw DDL below).
    #        A standard UniqueConstraint treats NULLs as equal, which would
    #        wrongly block multiple NULL-TA sessions. The partial index only
    #        enforces uniqueness where ta_id IS NOT NULL.
    #
    # FK delete rules:
    #   timetable_id  → CASCADE  (timetable deleted → all entries deleted)
    #   assignment_id → CASCADE  (assignment deleted → its entries deleted)
    #   room_id       → RESTRICT (prevent deleting a room with live entries)
    #   section_id    → RESTRICT
    #   faculty_id    → RESTRICT
    #   ta_id         → SET NULL (TA deleted → entry remains, ta_id=null)
    # ════════════════════════════════════════════════════════════════════════

    op.create_table(
        "timetable_entries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "timetable_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("timetables.id",        ondelete="CASCADE",  name="fk_te_timetable_id"),
            nullable=False,
        ),
        sa.Column(
            "assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("course_assignments.id", ondelete="CASCADE",  name="fk_te_assignment_id"),
            nullable=False,
        ),
        sa.Column(
            "session_type",
            postgresql.ENUM("LECTURE", "TUTORIAL", "LAB", name="session_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "day",
            postgresql.ENUM("MON", "TUE", "WED", "THU", "FRI", name="day_of_week", create_type=False),
            nullable=False,
        ),
        # Integer hour of session start: 8–17
        sa.Column("start_slot", sa.SmallInteger, nullable=False),
        # Integer hour of session end: 9–18 (always > start_slot)
        sa.Column("end_slot",   sa.SmallInteger, nullable=False),
        sa.Column(
            "room_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rooms.id",    ondelete="RESTRICT", name="fk_te_room_id"),
            nullable=False,
        ),
        # Denormalized from CourseAssignment
        sa.Column(
            "section_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sections.id", ondelete="RESTRICT", name="fk_te_section_id"),
            nullable=False,
        ),
        sa.Column(
            "faculty_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id",    ondelete="RESTRICT", name="fk_te_faculty_id"),
            nullable=False,
        ),
        # Null for LECTURE and LAB sessions; populated for TUTORIAL sessions
        sa.Column(
            "ta_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id",    ondelete="SET NULL", name="fk_te_ta_id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Domain constraints
        sa.CheckConstraint("start_slot BETWEEN 8 AND 17", name="ck_te_start_slot_range"),
        sa.CheckConstraint("end_slot BETWEEN 9 AND 18",   name="ck_te_end_slot_range"),
        sa.CheckConstraint("end_slot > start_slot",        name="ck_te_end_after_start"),
        # ── Resource-clash unique constraints (non-partial) ──────────
        # 1. No room double-booking
        sa.UniqueConstraint(
            "timetable_id", "room_id",    "day", "start_slot",
            name="uq_te_room_day_slot",
        ),
        # 2. No section clash
        sa.UniqueConstraint(
            "timetable_id", "section_id", "day", "start_slot",
            name="uq_te_section_day_slot",
        ),
        # 3. No faculty clash
        sa.UniqueConstraint(
            "timetable_id", "faculty_id", "day", "start_slot",
            name="uq_te_faculty_day_slot",
        ),
        # 4. No TA clash — PARTIAL unique index created below via raw DDL
    )

    # Read-path indexes
    op.create_index("idx_te_timetable_id",  "timetable_entries", ["timetable_id"])
    op.create_index("idx_te_section_day",   "timetable_entries", ["timetable_id", "section_id", "day"])
    op.create_index("idx_te_faculty_day",   "timetable_entries", ["timetable_id", "faculty_id", "day"])
    op.create_index("idx_te_room_day",      "timetable_entries", ["timetable_id", "room_id",    "day"])
    op.create_index("idx_te_ta_id",         "timetable_entries", ["timetable_id", "ta_id"])
    op.create_index("idx_te_assignment_id", "timetable_entries", ["assignment_id"])

    # ── Partial unique index 4: no TA clash (WHERE ta_id IS NOT NULL) ────
    # Standard UniqueConstraint would treat NULL == NULL, wrongly blocking
    # multiple sessions with no TA assigned (ta_id=NULL). This partial index
    # only enforces uniqueness on rows where a TA is actually set.
    op.execute("""
        CREATE UNIQUE INDEX uq_te_ta_day_slot
            ON timetable_entries (timetable_id, ta_id, day, start_slot)
            WHERE ta_id IS NOT NULL;
    """)

    # ════════════════════════════════════════════════════════════════════════
    # 13. TABLE: conflict_reports
    #
    # 1:1 with timetables. Stores the JSONB array output of conflict.py.
    # JSONB is used here (and only here) because:
    #   - The report is always read as a unit (never filtered by column)
    #   - blocking_constraints is a variable-length list (hard to normalise)
    #   - New reason_codes require no schema change
    # ════════════════════════════════════════════════════════════════════════

    op.create_table(
        "conflict_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "timetable_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("timetables.id", ondelete="CASCADE", name="fk_conflict_reports_timetable_id"),
            nullable=False,
            unique=True,   # 1:1 with timetable
        ),
        # [] = empty array = conflict-free generation
        sa.Column(
            "report",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # B-tree: "get the conflict report for timetable X"
    op.create_index("idx_cr_timetable_id", "conflict_reports", ["timetable_id"])
    # GIN: enables JSONB path queries e.g. WHERE report @> '[{"reason_code":"NO_ROOM"}]'
    op.create_index(
        "idx_cr_report_gin",
        "conflict_reports",
        ["report"],
        postgresql_using="gin",
    )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Drop in reverse FK dependency order.
    # Partial indexes (uq_te_ta_day_slot, uq_timetables_active_per_semester)
    # are automatically dropped when their parent table is dropped.

    op.drop_table("conflict_reports")
    op.drop_table("timetable_entries")
    op.drop_table("timetables")
    op.drop_table("course_assignments")
    op.drop_table("ta_availability")
    op.drop_table("faculty_availability")
    op.drop_table("courses")
    op.drop_table("rooms")
    op.drop_table("sections")
    op.drop_table("semesters")
    op.drop_table("users")

    # Drop trigger function after all tables referencing it are gone
    op.execute("DROP FUNCTION IF EXISTS set_updated_at CASCADE;")

    # Drop enum types — must happen after all referencing tables are dropped
    op.execute("DROP TYPE IF EXISTS timetable_status;")
    op.execute("DROP TYPE IF EXISTS day_of_week;")
    op.execute("DROP TYPE IF EXISTS session_type;")
    op.execute("DROP TYPE IF EXISTS room_type;")
    op.execute("DROP TYPE IF EXISTS course_tier;")
    op.execute("DROP TYPE IF EXISTS user_role;")
