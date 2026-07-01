"""
api/assignments.py — Admin-only Course Assignment endpoints.

All endpoints require role = ADMIN (enforced via Depends(require_admin)).

Endpoint map:

  POST   /api/v1/assignments                     Create a course assignment
  GET    /api/v1/assignments                     List assignments (with filters)
  GET    /api/v1/assignments/{assignment_id}     Get a single assignment by UUID
  PATCH  /api/v1/assignments/{assignment_id}     Update faculty and/or TA
  DELETE /api/v1/assignments/{assignment_id}     Delete an assignment (CASCADE)

Design principles:
  - Thin routes: validate → call service → return schema.
  - ValueError → HTTP status via _handle_value_error helper.
  - Every mutating route wraps in try/commit + except/rollback.
  - All endpoints have unique operation_id for OpenAPI client generation.

Notes on the assignment lifecycle:
  CREATE:
    Validate course, section, faculty, TA existence and roles.
    Check (course_id, section_id) uniqueness.
    This is the most validation-heavy create in the entire API.

  UPDATE:
    Only faculty_id and ta_id are updatable.
    course_id and section_id are immutable — DELETE + POST instead.
    An empty body {} is a valid no-op.

  DELETE:
    CASCADE: all timetable entries for this assignment are also deleted.
    No RESTRICT FK on assignment_id → no 409 risk.

  LIST:
    Optional query filters: ?course_id=, ?section_id=, ?faculty_id=
    Multiple filters are AND-ed together.
    Supports ?skip and ?limit pagination.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.models.user import User
from app.schemas.course_assignment import (
    AssignmentCreate,
    AssignmentListResponse,
    AssignmentRead,
    AssignmentUpdate,
)
from app.services import course_assignment_service

router = APIRouter(
    prefix="/assignments",
    tags=["assignments"],
)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _handle_value_error(exc: ValueError) -> HTTPException:
    """
    Convert a service-layer ValueError to the appropriate HTTPException.

    Mapping:
      message contains "not found"         → 404 Not Found
      message contains "already assigned"  → 409 Conflict
      anything else                        → 400 Bad Request

    Business rules (tier rule, wrong role, not active) map to 400 Bad Request
    because the request is structurally valid but violates a business constraint.
    This matches REST semantics: 409 is for duplicate resource conflicts;
    400 is for requests that violate business rules.
    """
    message = str(exc)
    low = message.lower()

    if "not found" in low or "not active" in low:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=message,
        )
    if "already assigned" in low:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=message,
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=message,
    )


# ── POST /assignments — Create ────────────────────────────────────────────────

@router.post(
    "",
    response_model=AssignmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create course assignment",
    description=(
        "Admin-only. Assign a course to a section with a faculty member and optional TA. "
        "TAs are optional across all tiers. "
        "A course can only be assigned to each section once."
    ),
    operation_id="create_assignment",
)
async def create_assignment(
    body: AssignmentCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> AssignmentRead:
    """
    Create a course assignment.

    201 Created  — assignment created.
    400 Bad Request — wrong role, inactive user.
    404 Not Found   — course, section, faculty, or TA UUID not found.
    409 Conflict    — (course_id, section_id) already exists.
    422 Unprocessable — malformed UUID in body.
    """
    try:
        assignment = await course_assignment_service.create_assignment(
            db=db,
            data=body,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return AssignmentRead.model_validate(assignment)


# ── GET /assignments — List ───────────────────────────────────────────────────

@router.get(
    "",
    response_model=AssignmentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List course assignments",
    description=(
        "Admin-only. List course assignments with optional filters. "
        "All filters are optional and AND-ed together. "
        "Supports ?skip and ?limit pagination."
    ),
    operation_id="list_assignments",
)
async def list_assignments(
    course_id: uuid.UUID | None = Query(
        default=None,
        description="Filter by course UUID.",
    ),
    section_id: uuid.UUID | None = Query(
        default=None,
        description="Filter by section UUID.",
    ),
    faculty_id: uuid.UUID | None = Query(
        default=None,
        description="Filter by faculty UUID.",
    ),
    skip: int = Query(default=0, ge=0, description="Number of records to skip."),
    limit: int = Query(default=100, ge=1, le=200, description="Max records per page (1–200)."),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> AssignmentListResponse:
    """
    Return a paginated list of assignments.

    200 OK — always (empty list if no assignments match).
    """
    total, assignments = await course_assignment_service.list_assignments(
        db=db,
        course_id=course_id,
        section_id=section_id,
        faculty_id=faculty_id,
        skip=skip,
        limit=limit,
    )
    return AssignmentListResponse(
        total=total,
        items=[AssignmentRead.model_validate(a) for a in assignments],
    )


# ── GET /assignments/{assignment_id} — Get single ─────────────────────────────

@router.get(
    "/{assignment_id}",
    response_model=AssignmentRead,
    status_code=status.HTTP_200_OK,
    summary="Get assignment",
    description="Admin-only. Return a single course assignment by UUID.",
    operation_id="get_assignment",
)
async def get_assignment(
    assignment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> AssignmentRead:
    """
    Return a single assignment by UUID.

    200 OK        — assignment found.
    404 Not Found — no assignment with that UUID.
    """
    assignment = await course_assignment_service.get_assignment_by_id(
        db=db,
        assignment_id=assignment_id,
    )
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assignment {assignment_id} not found.",
        )
    return AssignmentRead.model_validate(assignment)


# ── PATCH /assignments/{assignment_id} — Update ───────────────────────────────

@router.patch(
    "/{assignment_id}",
    response_model=AssignmentRead,
    status_code=status.HTTP_200_OK,
    summary="Update assignment",
    description=(
        "Admin-only. Update the faculty member and/or TA for an assignment. "
        "course_id and section_id cannot be changed — delete and recreate instead. "
        "TAs are optional across all tiers. "
        "An empty body {} is a valid no-op."
    ),
    operation_id="update_assignment",
)
async def update_assignment(
    assignment_id: uuid.UUID,
    body: AssignmentUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> AssignmentRead:
    """
    Update faculty and/or TA of an assignment.

    200 OK        — update applied (or no-op if body was empty).
    400 Bad Request — wrong role.
    404 Not Found   — assignment not found, faculty not found, TA not found.
    """
    try:
        assignment = await course_assignment_service.update_assignment(
            db=db,
            assignment_id=assignment_id,
            data=body,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return AssignmentRead.model_validate(assignment)


# ── DELETE /assignments/{assignment_id} — Hard delete ─────────────────────────

@router.delete(
    "/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete assignment",
    description=(
        "Admin-only. Permanently delete a course assignment. "
        "All timetable entries associated with this assignment "
        "are automatically deleted via CASCADE. "
        "This action is irreversible."
    ),
    operation_id="delete_assignment",
)
async def delete_assignment(
    assignment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    """
    Hard-delete an assignment and all its cascaded timetable entries.

    204 No Content — assignment deleted.
    404 Not Found  — no assignment with that UUID.
    """
    try:
        await course_assignment_service.delete_assignment(
            db=db,
            assignment_id=assignment_id,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)
