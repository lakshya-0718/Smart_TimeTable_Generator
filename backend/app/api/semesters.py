"""
api/semesters.py — Admin-only Semester Management endpoints.

All endpoints require role = ADMIN (enforced via Depends(require_admin)).

Endpoint map:

  POST   /api/v1/semesters                       Create a semester
  GET    /api/v1/semesters                       List all semesters
  GET    /api/v1/semesters/active                Get the currently active semester
  GET    /api/v1/semesters/{semester_id}         Get a single semester by UUID
  PATCH  /api/v1/semesters/{semester_id}         Update semester name
  DELETE /api/v1/semesters/{semester_id}         Delete a semester (hard delete)
  POST   /api/v1/semesters/{semester_id}/set-active    Mark semester as active
  POST   /api/v1/semesters/{semester_id}/unset-active  Deactivate without replacing

IMPORTANT — route ordering:
  GET /semesters/active MUST be declared BEFORE GET /semesters/{semester_id}.
  FastAPI matches routes top-to-bottom.  If /{semester_id} is declared first,
  the string "active" would be captured as a UUID path parameter and fail
  validation with a 422 Unprocessable Entity.  Declaring /active first ensures
  it is matched as a literal path before the dynamic segment.

Design principles:
  - Thin routes: validate → call service → return schema.
  - ValueError → HTTP status via _handle_value_error helper.
  - Every mutating route wraps in try/commit + except/rollback.
  - All endpoints have unique operation_id for OpenAPI client generation.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.models.user import User
from app.schemas.semester import SemesterCreate, SemesterRead, SemesterUpdate
from app.services import semester_service

router = APIRouter(
    prefix="/semesters",
    tags=["semesters"],
)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _handle_value_error(exc: ValueError) -> HTTPException:
    """
    Convert a service-layer ValueError to the appropriate HTTPException.

    Mapping:
      message contains "not found"       → 404 Not Found
      message contains "already taken"   → 409 Conflict
      message contains "cannot delete"   → 409 Conflict (protecting active semester)
      anything else                      → 400 Bad Request
    """
    message = str(exc)
    low = message.lower()

    if "not found" in low:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=message,
        )
    if "already taken" in low or "cannot delete" in low:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=message,
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=message,
    )


# ── POST /semesters — Create ──────────────────────────────────────────────────

@router.post(
    "",
    response_model=SemesterRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create semester",
    description=(
        "Admin-only. Create a new semester. "
        "The semester starts inactive (is_active=False). "
        "Use POST /semesters/{id}/set-active to make it the working semester."
    ),
    operation_id="create_semester",
)
async def create_semester(
    body: SemesterCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> SemesterRead:
    """
    Create a new semester.

    201 Created  — semester created.
    409 Conflict — name is already taken.
    """
    try:
        semester = await semester_service.create_semester(db=db, data=body)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return SemesterRead.model_validate(semester)


# ── GET /semesters — List all ─────────────────────────────────────────────────

@router.get(
    "",
    response_model=list[SemesterRead],
    status_code=status.HTTP_200_OK,
    summary="List semesters",
    description=(
        "Admin-only. Return all semesters ordered by name. "
        "No pagination — semesters are a small, finite set. "
        "The active semester is identified by is_active=True in the response."
    ),
    operation_id="list_semesters",
)
async def list_semesters(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[SemesterRead]:
    """
    Return all semesters.

    200 OK — always (empty list if no semesters exist yet).
    """
    semesters = await semester_service.list_semesters(db=db)
    return [SemesterRead.model_validate(s) for s in semesters]


# ── GET /semesters/active — Get the active semester ───────────────────────────
# MUST be declared before /{semester_id} to avoid "active" being parsed as UUID.

@router.get(
    "/active",
    response_model=SemesterRead,
    status_code=status.HTTP_200_OK,
    summary="Get active semester",
    description=(
        "Admin-only. Return the currently active semester. "
        "Returns 404 if no semester has been set as active yet."
    ),
    operation_id="get_active_semester",
)
async def get_active_semester(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> SemesterRead:
    """
    Return the active semester.

    200 OK        — active semester found.
    404 Not Found — no semester is currently active.
    """
    semester = await semester_service.get_active_semester(db=db)
    if semester is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active semester. Use POST /semesters/{id}/set-active to activate one.",
        )
    return SemesterRead.model_validate(semester)


# ── GET /semesters/{semester_id} — Get a single semester ─────────────────────

@router.get(
    "/{semester_id}",
    response_model=SemesterRead,
    status_code=status.HTTP_200_OK,
    summary="Get semester",
    description="Admin-only. Return a single semester by UUID.",
    operation_id="get_semester",
)
async def get_semester(
    semester_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> SemesterRead:
    """
    Return a single semester by UUID.

    200 OK        — semester found.
    404 Not Found — no semester with that UUID.
    """
    semester = await semester_service.get_semester_by_id(db=db, semester_id=semester_id)
    if semester is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Semester {semester_id} not found.",
        )
    return SemesterRead.model_validate(semester)


# ── PATCH /semesters/{semester_id} — Update name ─────────────────────────────

@router.patch(
    "/{semester_id}",
    response_model=SemesterRead,
    status_code=status.HTTP_200_OK,
    summary="Update semester",
    description=(
        "Admin-only. Rename a semester. "
        "Only `name` is updatable here. "
        "An empty body is a valid no-op."
    ),
    operation_id="update_semester",
)
async def update_semester(
    semester_id: uuid.UUID,
    body: SemesterUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> SemesterRead:
    """
    Rename a semester.

    200 OK        — update applied (or no-op if body was empty).
    404 Not Found — no semester with that UUID.
    409 Conflict  — new name is already taken.
    """
    try:
        semester = await semester_service.update_semester(
            db=db,
            semester_id=semester_id,
            data=body,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return SemesterRead.model_validate(semester)


# ── DELETE /semesters/{semester_id} — Hard delete ─────────────────────────────

@router.delete(
    "/{semester_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete semester",
    description=(
        "Admin-only. Permanently delete a semester and ALL its data "
        "(courses, assignments, timetables, entries, conflict reports). "
        "Cannot delete the active semester — deactivate it first. "
        "This action is irreversible."
    ),
    operation_id="delete_semester",
)
async def delete_semester(
    semester_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    """
    Hard-delete a semester and its cascaded data.

    204 No Content — semester deleted.
    404 Not Found  — no semester with that UUID.
    409 Conflict   — the semester is currently active (deactivate first).
    """
    try:
        await semester_service.delete_semester(db=db, semester_id=semester_id)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)


# ── POST /semesters/{semester_id}/set-active ──────────────────────────────────

@router.post(
    "/{semester_id}/set-active",
    response_model=SemesterRead,
    status_code=status.HTTP_200_OK,
    summary="Set semester active",
    description=(
        "Admin-only. Mark this semester as the active working semester. "
        "All other semesters are automatically deactivated in the same transaction. "
        "Idempotent: setting the already-active semester to active is a no-op."
    ),
    operation_id="set_semester_active",
)
async def set_active(
    semester_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> SemesterRead:
    """
    Activate a semester (deactivating all others atomically).

    200 OK        — semester is now active.
    404 Not Found — no semester with that UUID.
    """
    try:
        semester = await semester_service.set_active(db=db, semester_id=semester_id)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return SemesterRead.model_validate(semester)


# ── POST /semesters/{semester_id}/unset-active ────────────────────────────────

@router.post(
    "/{semester_id}/unset-active",
    response_model=SemesterRead,
    status_code=status.HTTP_200_OK,
    summary="Unset semester active",
    description=(
        "Admin-only. Deactivate this semester without activating any other. "
        "After this call, no semester will be active. "
        "Idempotent: calling on an already-inactive semester returns 200."
    ),
    operation_id="unset_semester_active",
)
async def unset_active(
    semester_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> SemesterRead:
    """
    Deactivate a semester (without replacing it with another).

    200 OK        — semester is now inactive.
    404 Not Found — no semester with that UUID.
    """
    try:
        semester = await semester_service.unset_active(db=db, semester_id=semester_id)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return SemesterRead.model_validate(semester)
