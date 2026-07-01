"""
schemas/course_assignment.py — Pydantic models for the Course Assignment API.

Schema hierarchy:

  Inbound (request bodies):
    AssignmentCreate — Admin creates a new course assignment.
    AssignmentUpdate — Admin updates faculty and/or TA on an assignment.

  Outbound (response bodies):
    AssignmentRead         — Public representation of one assignment record.
    AssignmentListResponse — Paginated list of assignments.

Design decisions:

  The TA tier rule (Removed):
    Previously, TIER_1/2 required a TA and TIER_3/4 prohibited it.
    This constraint has been removed. TAs are now completely optional 
    across all tiers. If assigned, they will participate in Tutorials and Labs.



  Why can't course_id and section_id be updated?
    A course assignment IS the binding of a course to a section.  Changing
    course_id or section_id would mean "re-point this assignment to a
    different course or section", which is indistinguishable from creating a
    new assignment and deleting the old one.  The unique constraint
    (course_id, section_id) would also require checking the new combination.
    The correct workflow is: DELETE the old assignment, POST the new one.

  Why are faculty_id and ta_id updatable?
    These are the personnel assignments within the fixed course-section binding.
    Faculty might be swapped (course reassignment between professors) and
    TA reassignment is explicitly documented in the schema design notes
    (ta_id SET NULL pattern).

  AssignmentRead returns only UUIDs (not nested objects):
    Nesting full CourseRead, SectionRead, UserRead objects would make this
    response very heavy — the frontend has all these objects cached already.
    UUID references are the correct REST pattern at this level.
    The frontend joins them client-side for display.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ── Inbound ───────────────────────────────────────────────────────────────────

class AssignmentCreate(BaseModel):
    """
    Request body for POST /assignments.

    All four FKs are present here. ta_id is completely optional.

    Structural validation (can be done without a DB hit):
      - All UUIDs must be valid UUID format (Pydantic type check)
      - ta_id=None is accepted here — the service validates the tier rule.

    Semantic validation (requires DB lookup, done in service):
      - course_id must reference an existing Course
      - section_id must reference an existing Section
      - faculty_id must reference an active User with role=FACULTY
      - ta_id (if provided) must reference an active User with role=TA
      - (course_id, section_id) must be unique
    """

    course_id: uuid.UUID = Field(
        ...,
        description="UUID of the course to assign.",
    )
    section_id: uuid.UUID = Field(
        ...,
        description="UUID of the section to assign the course to.",
    )
    faculty_id: uuid.UUID = Field(
        ...,
        description="UUID of the Faculty user who will teach lectures (and labs for TIER_1).",
    )
    ta_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "UUID of the TA who will teach tutorials and/or labs. "
            "Optional for all tiers."
        ),
    )


class AssignmentUpdate(BaseModel):
    """
    Request body for PATCH /assignments/{assignment_id}.

    Only faculty_id and ta_id are updatable.
    course_id and section_id define the assignment's structural identity
    and cannot change — see module docstring for rationale.

    An empty body {} is a valid no-op.

    The service re-validates:
      - If faculty_id is changed, it must be valid.
      - If ta_id is changed, it must be valid.

    Note on ta_id=null in PATCH:
      In JSON, {"ta_id": null} means "set ta_id to None".
      This is distinct from omitting ta_id entirely (no-op).
      We use `model_fields_set` in the service to distinguish these cases.
    """

    faculty_id: uuid.UUID | None = Field(
        default=None,
        description="New Faculty UUID to assign. Must have role=FACULTY.",
    )
    ta_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "New TA UUID. Must have role=TA. "
            "Set to null to remove TA."
        ),
    )


# ── Outbound ──────────────────────────────────────────────────────────────────

class AssignmentRead(BaseModel):
    """
    Public representation of a CourseAssignment record.

    Returns UUID references for related entities, not nested objects.
    The frontend already has Course, Section, and User data cached and
    joins them locally for display.

    Fields:
      id         — Assignment UUID (primary key).
      course_id  — The assigned course.
      section_id — The assigned section.
      faculty_id — The assigned faculty member.
      ta_id      — The assigned TA (optional).
      created_at / updated_at — Timestamps.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    course_id: uuid.UUID
    section_id: uuid.UUID
    faculty_id: uuid.UUID
    ta_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class AssignmentListResponse(BaseModel):
    """
    Paginated list of course assignments.

    `total` is the count of all matching assignments before pagination.
    `items` is the current page.

    The list endpoint accepts optional filters:
      - course_id:  show all section assignments for one course
      - section_id: show all courses assigned to one section
      - faculty_id: show all courses taught by one faculty member
    Multiple filters are AND-ed together.
    """

    total: int = Field(..., description="Total matching assignments.")
    items: list[AssignmentRead] = Field(..., description="Assignments on the current page.")
