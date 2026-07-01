"""
schemas/course.py — Pydantic models for the Course Management API.

Schema hierarchy:

  Inbound (request bodies):
    CourseCreate — Admin creates a new course in a semester.
    CourseUpdate — Admin partially updates course details (PATCH).

  Outbound (response bodies):
    CourseRead         — Public representation of a course record.
    CourseListResponse — Paginated list of courses (scoped to a semester).

Design decisions:

  Why is `semester_id` not updatable via PATCH?
    A course's semester membership is its primary structural context.
    Moving a course to a different semester would orphan any existing
    course_assignments (which reference both course_id and a section),
    and could silently corrupt a timetable that is in progress.
    If admin needs to move a course, the correct workflow is:
      1. Delete the course (cascades its assignments and timetable entries).
      2. Recreate it in the target semester.
    This intent-clarity is worth the extra step.

  Why is CourseListResponse a paginated wrapper?
    Unlike semesters (≤20) or sections (=8), courses are genuinely
    open-ended within a semester.  A busy department offering 50+ courses
    in a term benefits from pagination and a total count.  The wrapper
    follows the same shape as UserListResponse for frontend consistency.

  Why is `code` stripped and uppercased on inbound?
    Course codes are typically uppercase ("CS301", "MA201").  Normalising
    at the schema layer prevents duplicates caused by case variation:
    "cs301" and "CS301" would otherwise both pass the uniqueness check
    but represent the same course.

  Why is tier validated against CourseTier (from models/enums)?
    The same enum is used by the Course ORM model and the scheduler's
    context.py.  Sharing the enum definition in models/enums.py is the
    single source of truth.

Validation rules:
  - name:  stripped, 1–200 chars (mirrors VARCHAR(200))
  - code:  stripped, uppercased, 1–20 chars (mirrors VARCHAR(20))
  - tier:  must be TIER_1 | TIER_2 | TIER_3 | TIER_4 (enum)
  - semester_id: required UUID on create, not on update
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import CourseTier


# ── Inbound ───────────────────────────────────────────────────────────────────

class CourseCreate(BaseModel):
    """
    Request body for POST /courses.

    All fields are required — there is no sensible default for any of them.

    The composite uniqueness rule (semester_id, code) is enforced at the
    service layer before insertion, giving a clear 409 error rather than
    an opaque IntegrityError from the DB.

    tier represents the full L-T-P encoding:
      TIER_1 → 4-credit: 3 lectures + 1 tutorial + 1 lab (3-slot)
      TIER_2 → 3-credit: 3 lectures + 1 tutorial (no lab)
      TIER_3 → 2-credit: 1 lab (4-slot, lab-only)
      TIER_4 → 1-credit: 1 lab (2-slot, lab-only)
    """

    semester_id: uuid.UUID = Field(
        ...,
        description="UUID of the semester this course belongs to.",
        examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Full course name, e.g. 'Data Structures and Algorithms'.",
        examples=["Data Structures and Algorithms"],
    )
    code: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Short course code, e.g. 'CS301'. Must be unique within the semester.",
        examples=["CS301"],
    )
    tier: CourseTier = Field(
        ...,
        description=(
            "L-T-P tier: TIER_1 (4-credit), TIER_2 (3-credit), "
            "TIER_3 (2-credit lab-only), TIER_4 (1-credit lab-only)."
        ),
        examples=[CourseTier.TIER_1],
    )

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str) -> str:
        """Strip whitespace from both ends of the course name."""
        return v.strip()

    @field_validator("code", mode="before")
    @classmethod
    def normalise_code(cls, v: str) -> str:
        """
        Strip whitespace and uppercase the code.

        Prevents case-variation duplicates: 'cs301' and 'CS301' would
        both pass (semester_id, code) uniqueness checks if not normalised.
        The DB uniqueness constraint is case-sensitive in PostgreSQL, so
        normalising here is essential.
        """
        return v.strip().upper()


class CourseUpdate(BaseModel):
    """
    Request body for PATCH /courses/{course_id}.

    All fields are optional.  The service uses model_fields_set to update
    only explicitly-provided fields (PATCH semantics).
    An empty body {} is a valid no-op.

    Updatable fields: name, code, tier.
    NOT updatable: semester_id — see module docstring for rationale.

    code re-checks (semester_id, code) uniqueness if changed.
    """

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Updated course name.",
        examples=["Advanced Data Structures"],
    )
    code: str | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        description="Updated course code. Must be unique within the semester.",
        examples=["CS302"],
    )
    tier: CourseTier | None = Field(
        default=None,
        description="Updated tier.",
        examples=[CourseTier.TIER_2],
    )

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip()

    @field_validator("code", mode="before")
    @classmethod
    def normalise_code(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip().upper()


# ── Outbound ──────────────────────────────────────────────────────────────────

class CourseRead(BaseModel):
    """
    Public representation of a Course record.

    Returned by all course endpoints.

    Includes semester_id so the frontend can group courses by semester
    without a join, and tier so the timetable grid can display the
    correct session pattern per course.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    semester_id: uuid.UUID
    name: str
    code: str
    tier: CourseTier
    created_at: datetime
    updated_at: datetime


class CourseListResponse(BaseModel):
    """
    Paginated list of courses scoped to a semester.

    `total` is the count of all matching courses before pagination.
    `items` is the current page.
    `semester_id` is echoed so the frontend can correlate the response
    to the query without re-reading the request URL.
    """

    semester_id: uuid.UUID = Field(..., description="Semester the courses belong to.")
    total: int = Field(..., description="Total courses in this semester.")
    items: list[CourseRead] = Field(..., description="Courses on the current page.")
