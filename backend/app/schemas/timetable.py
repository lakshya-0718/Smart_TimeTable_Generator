"""
schemas/timetable.py — Pydantic models for the Timetable API.

Schema hierarchy:

  Inbound (request bodies):
    GenerateRequest       — Body for POST /timetable/generate.

  Outbound (response bodies):
    TimetableRead         — Header record for one timetable.
    TimetableEntryRead    — One scheduled session row.
    ConflictItemRead      — One unscheduled session item from the JSONB report.
    ConflictReportRead    — Full conflict report for a timetable.
    GenerateResponse      — Returned by POST /timetable/generate.
    TimetableEntriesResponse — Paginated + filtered list of entries.

  Enums:
    ExportType            — Section | Faculty | Room | Full (for CSV export).
    EntryFilterType       — How to filter entries for the grid view.

Design decisions:

  GenerateRequest carries semester_id explicitly.
    Although generation implicitly targets the active semester, requiring the
    admin to send the semester_id prevents accidental generation against the
    wrong semester if "active" was recently toggled.

  TimetableEntryRead includes all 12 columns.
    The entry table is denormalised by design (section_id, faculty_id, ta_id
    are copied from CourseAssignment). All 12 columns are returned so the
    frontend grid renderer never needs to make a separate lookup.
    Note: NO updated_at — TimetableEntry uses UUIDPKCreatedAtMixin
    (created_at only; entries are immutable after generation).

  ConflictItemRead is typed per the JSONB structure in the model.
    This gives the frontend type-safe conflict item parsing.
    The `blocking_constraints` list is kept as list[str] — the engine may
    add new constraint codes without a schema migration.

  ExportType enum drives the CSV endpoint filter parameter.
    SECTION: all entries for one section (most common export).
    FACULTY: all entries for one faculty member.
    ROOM:    all entries in one room.
    FULL:    all entries, no filter (generates one large CSV).
"""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.models.enums import DayOfWeek, SessionType, TimetableStatus


# ── Enums ─────────────────────────────────────────────────────────────────────

class ExportType(str, Enum):
    """
    CSV export scope selector.

    SECTION  — exports the timetable for one section (requires filter_id=section_uuid).
    FACULTY  — exports all sessions for one faculty member (requires filter_id=user_uuid).
    ROOM     — exports all sessions in one room (requires filter_id=room_uuid).
    FULL     — exports all entries with no filter.
    """
    SECTION = "SECTION"
    FACULTY = "FACULTY"
    ROOM = "ROOM"
    FULL = "FULL"


# ── Inbound ───────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    """
    Request body for POST /timetable/generate.

    semester_id is required to prevent accidental generation against the
    wrong semester when the active flag has just been toggled.
    The service additionally validates that this semester's is_active=True.
    """
    semester_id: uuid.UUID = Field(
        ...,
        description="UUID of the active semester to generate a timetable for.",
    )


# ── Outbound ──────────────────────────────────────────────────────────────────

class TimetableRead(BaseModel):
    """
    Header record for a generated timetable.

    Returned by GET /timetable/active and as part of GenerateResponse.

    Fields:
      id           — Timetable UUID.
      semester_id  — Which semester this timetable belongs to.
      status       — ACTIVE or SNAPSHOT.
      generated_at — When the scheduler ran.
      generated_by — UUID of the admin who triggered generation (nullable).
      created_at   — Row insertion timestamp.
      updated_at   — Last modification timestamp.
    """
    model_config = {"from_attributes": True}

    id: uuid.UUID
    semester_id: uuid.UUID
    status: TimetableStatus
    generated_at: datetime
    generated_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class TimetableEntryRead(BaseModel):
    """
    Public representation of one TimetableEntry row.

    Returned by GET /timetable/{id}/entries.

    All 12 columns are included — the frontend grid never needs to JOIN.
    Section_id, faculty_id, ta_id are denormalised from CourseAssignment
    at generation time; they are safe to return here since entries are
    immutable after insertion.

    Note: NO updated_at — TimetableEntry uses UUIDPKCreatedAtMixin
    (created_at only).
    """
    model_config = {"from_attributes": True}

    id: uuid.UUID
    timetable_id: uuid.UUID
    assignment_id: uuid.UUID
    session_type: SessionType
    day: DayOfWeek
    start_slot: int
    end_slot: int
    room_id: uuid.UUID
    section_id: uuid.UUID
    faculty_id: uuid.UUID
    ta_id: uuid.UUID | None
    created_at: datetime


class ConflictItemRead(BaseModel):
    """
    One item from the JSONB conflict report.

    Typed to match the structure documented in ConflictReport.report:
    {
        "assignment_id":        "<uuid>",
        "course_code":          "CS301",
        "course_name":          "Data Structures",
        "section":              "Y2A",
        "session_type":         "LAB",
        "reason_code":          "NO_VALID_ROOM",
        "reason_detail":        "No LAB room with capacity >= 65...",
        "blocking_constraints": ["ROOM_CAPACITY", "LAB_CONSECUTIVE"]
    }

    `blocking_constraints` is list[str] — flexible for new engine codes.
    All fields are Optional because JSONB parsing should not fail if the
    engine adds new fields or omits optional ones in edge cases.
    """
    assignment_id: str | None = None
    course_code: str | None = None
    course_name: str | None = None
    section: str | None = None
    session_type: str | None = None
    reason_code: str | None = None
    reason_detail: str | None = None
    blocking_constraints: list[str] = Field(default_factory=list)


class ConflictReportRead(BaseModel):
    """
    Full conflict report for a timetable.

    Returned by GET /timetable/{id}/conflicts.

    `total` = number of unscheduled sessions.
    `conflicts` = parsed list of ConflictItemRead objects.
    An empty `conflicts` list means the timetable is fully conflict-free.
    """
    timetable_id: uuid.UUID
    total: int
    conflicts: list[ConflictItemRead]


class TimetableEntriesResponse(BaseModel):
    """
    Paginated list of timetable entries, optionally filtered.

    Returned by GET /timetable/{id}/entries.

    Supports filters:
      section_id  — entries for one section
      faculty_id  — entries for one faculty member
      room_id     — entries for one room
      day         — entries on one day of the week
    Multiple filters are AND-ed.
    """
    timetable_id: uuid.UUID
    total: int
    items: list[TimetableEntryRead]


class GenerateResponse(BaseModel):
    """
    Response from POST /timetable/generate.

    Returns enough information for the frontend to:
      1. Navigate to the timetable viewer (timetable_id).
      2. Display pre-generation warnings (warnings).
      3. Decide whether to show the conflict tab (conflict_count > 0).

    Fields:
      timetable_id   — UUID of the newly ACTIVE timetable.
      warnings       — Pre-generation feasibility warnings (non-blocking).
                       e.g. ["Section Y2A: total weekly slots = 47 > 45 maximum"]
      conflict_count — Number of sessions the scheduler could not place.
                       0 = fully conflict-free schedule.
      snapshot_id    — UUID of the previous timetable archived as SNAPSHOT.
                       None if this is the first generation for the semester.
    """
    timetable_id: uuid.UUID
    warnings: list[str] = Field(default_factory=list)
    conflict_count: int
    snapshot_id: uuid.UUID | None = None
