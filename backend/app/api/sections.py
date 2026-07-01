"""
api/sections.py — Admin-only Section Management endpoints.

All endpoints require role = ADMIN (enforced via Depends(require_admin)).

Endpoint map:

  POST   /api/v1/sections                  Create a section (Y1A–Y4B)
  GET    /api/v1/sections                  List all sections
  GET    /api/v1/sections/{section_id}     Get a single section by UUID
  PATCH  /api/v1/sections/{section_id}     Update section strength
  DELETE /api/v1/sections/{section_id}     Delete a section (hard delete)

Design principles:
  - Thin routes: validate → call service → return schema.
  - ValueError → HTTP status via _handle_value_error helper.
  - Every mutating route wraps in try/commit + except/rollback.
  - All endpoints have unique operation_id for OpenAPI client generation.

Notes on the section lifecycle:
  - CREATE: Admin provides year, label, strength.  Name is derived by the
    service.  Only 8 sections should ever exist (Y1A–Y4B), but the API
    does not hard-limit this — the CHECK constraint on year (1–4) and
    label ('A'|'B') enforces the domain limit at the DB level.
  - UPDATE: Only strength is updatable.  Year, label, and name are fixed
    structural identifiers — changing them would require deleting and
    recreating the section.
  - DELETE: Blocked by RESTRICT FK if live course assignments exist.
    The service translates the IntegrityError to a 409 Conflict response.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.models.user import User
from app.schemas.section import SectionCreate, SectionRead, SectionUpdate
from app.services import section_service

router = APIRouter(
    prefix="/sections",
    tags=["sections"],
)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _handle_value_error(exc: ValueError) -> HTTPException:
    """
    Convert a service-layer ValueError to the appropriate HTTPException.

    Mapping:
      message contains "not found"              → 404 Not Found
      message contains "already exists"         → 409 Conflict
      message contains "cannot delete"          → 409 Conflict
      anything else                             → 400 Bad Request
    """
    message = str(exc)
    low = message.lower()

    if "not found" in low:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=message,
        )
    if "already exists" in low or "cannot delete" in low:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=message,
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=message,
    )


# ── POST /sections — Create ───────────────────────────────────────────────────

@router.post(
    "",
    response_model=SectionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create section",
    description=(
        "Admin-only. Create a new section. "
        "Provide year (1–4), label (A or B), and student strength. "
        "The section name (e.g. 'Y2A') is automatically derived. "
        "At most 8 sections exist in the system (Y1A–Y4B)."
    ),
    operation_id="create_section",
)
async def create_section(
    body: SectionCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> SectionRead:
    """
    Create a section.

    201 Created  — section created.
    409 Conflict — a section for this year/label already exists.
    422 Unprocessable — year out of 1–4, label not A/B, strength ≤ 0.
    """
    try:
        section = await section_service.create_section(db=db, data=body)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return SectionRead.model_validate(section)


# ── GET /sections — List all ──────────────────────────────────────────────────

@router.get(
    "",
    response_model=list[SectionRead],
    status_code=status.HTTP_200_OK,
    summary="List sections",
    description=(
        "Admin-only. Return all sections ordered by year then label "
        "(Y1A, Y1B, Y2A, Y2B, …, Y4B). "
        "No pagination — the system has at most 8 sections."
    ),
    operation_id="list_sections",
)
async def list_sections(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[SectionRead]:
    """
    Return all sections.

    200 OK — always (empty list if no sections created yet).
    """
    sections = await section_service.list_sections(db=db)
    return [SectionRead.model_validate(s) for s in sections]


# ── GET /sections/{section_id} — Get single ───────────────────────────────────

@router.get(
    "/{section_id}",
    response_model=SectionRead,
    status_code=status.HTTP_200_OK,
    summary="Get section",
    description="Admin-only. Return a single section by UUID.",
    operation_id="get_section",
)
async def get_section(
    section_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> SectionRead:
    """
    Return a single section by UUID.

    200 OK        — section found.
    404 Not Found — no section with that UUID.
    """
    section = await section_service.get_section_by_id(db=db, section_id=section_id)
    if section is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Section {section_id} not found.",
        )
    return SectionRead.model_validate(section)


# ── PATCH /sections/{section_id} — Update strength ───────────────────────────

@router.patch(
    "/{section_id}",
    response_model=SectionRead,
    status_code=status.HTTP_200_OK,
    summary="Update section",
    description=(
        "Admin-only. Update a section's student strength. "
        "Only `strength` is updatable. "
        "Year, label, and name are structural identifiers that cannot change. "
        "An empty body {} is a valid no-op."
    ),
    operation_id="update_section",
)
async def update_section(
    section_id: uuid.UUID,
    body: SectionUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> SectionRead:
    """
    Update a section's strength.

    200 OK        — update applied (or no-op if body was empty).
    404 Not Found — no section with that UUID.
    422 Unprocessable — strength ≤ 0.
    """
    try:
        section = await section_service.update_section(
            db=db,
            section_id=section_id,
            data=body,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return SectionRead.model_validate(section)


# ── DELETE /sections/{section_id} — Hard delete ───────────────────────────────

@router.delete(
    "/{section_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete section",
    description=(
        "Admin-only. Permanently delete a section. "
        "Blocked if any course assignments reference this section. "
        "Remove all course assignments for this section first."
    ),
    operation_id="delete_section",
)
async def delete_section(
    section_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    """
    Hard-delete a section.

    204 No Content — section deleted.
    404 Not Found  — no section with that UUID.
    409 Conflict   — live course assignments exist (RESTRICT FK).
    """
    try:
        await section_service.delete_section(db=db, section_id=section_id)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)
