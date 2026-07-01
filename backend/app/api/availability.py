"""
api/availability.py — Admin-only Availability Management endpoints.

All endpoints require role = ADMIN (enforced via Depends(require_admin)).

Endpoint map — Faculty:

  GET  /api/v1/availability/faculty/{user_id}
       Return all unavailability slots for a faculty member.

  PUT  /api/v1/availability/faculty/{user_id}
       Bulk-replace all unavailability slots for a faculty member.
       Body: {"slots": [{"day": "MON", "slot_hour": 10}, ...]}
       An empty list clears all unavailability.

  POST /api/v1/availability/faculty/{user_id}/slots
       Add a single unavailability slot.
       Body: {"day": "MON", "slot_hour": 10}

  DELETE /api/v1/availability/faculty/{user_id}/slots/{slot_id}
       Remove a single unavailability slot by UUID.

Endpoint map — TA (identical shape, different path prefix and role check):

  GET    /api/v1/availability/ta/{user_id}
  PUT    /api/v1/availability/ta/{user_id}
  POST   /api/v1/availability/ta/{user_id}/slots
  DELETE /api/v1/availability/ta/{user_id}/slots/{slot_id}

Design principles:
  - Thin routes: validate → call service → return schema.
  - ValueError → HTTP status via _handle_value_error helper.
  - Every mutating route wraps in try/commit + except/rollback.
  - All endpoints have unique operation_id for OpenAPI client generation.

Route ordering note:
  /{user_id}/slots/{slot_id} must be registered AFTER /{user_id} to avoid
  the path `/{user_id}/slots/{slot_id}` being matched by `/{user_id}`.
  FastAPI uses first-match routing. We register:
    GET    /{user_id}            — no conflict
    PUT    /{user_id}            — no conflict
    POST   /{user_id}/slots      — no conflict with above
    DELETE /{user_id}/slots/{slot_id} — no conflict with above

Why PUT for bulk-replace?
  HTTP semantics: PUT replaces the entire representation of a resource.
  The resource here is "the availability set for user X".  Sending a
  PUT with a complete new set is the idiomatic HTTP way to replace it.
  POST would imply appending; PATCH would imply partial update.
  PUT with full replacement is the correct verb for this pattern.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.models.user import User
from app.schemas.availability import (
    AvailabilityResponse,
    AvailabilitySlotRead,
    FacultyAvailabilityCreate,
    SlotInput,
    TAAvailabilityCreate,
)
from app.services import availability_service

router = APIRouter(
    prefix="/availability",
    tags=["availability"],
)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _handle_value_error(exc: ValueError) -> HTTPException:
    """
    Convert a service-layer ValueError to the appropriate HTTPException.

    Mapping:
      message contains "not found"       → 404 Not Found
      message contains "not active"      → 404 Not Found
        (deactivated users are treated as non-existent, per auth design)
      message contains "already exists"  → 409 Conflict
      anything else                      → 400 Bad Request
        (role mismatch — "has role 'ADMIN' but 'FACULTY' is required")
    """
    message = str(exc)
    low = message.lower()

    if "not found" in low or "not active" in low:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=message,
        )
    if "already exists" in low:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=message,
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=message,
    )


def _to_response(
    user_id: uuid.UUID,
    slots: list,
) -> AvailabilityResponse:
    """Build an AvailabilityResponse from a list of ORM slot objects."""
    return AvailabilityResponse(
        user_id=user_id,
        total=len(slots),
        slots=[AvailabilitySlotRead.model_validate(s) for s in slots],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Faculty Availability endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/faculty/{user_id}",
    response_model=AvailabilityResponse,
    status_code=status.HTTP_200_OK,
    summary="Get faculty availability",
    description=(
        "Admin-only. Return all unavailability slots for a faculty member. "
        "Returns an empty list if the faculty member has no blocked slots."
    ),
    operation_id="get_faculty_availability",
)
async def get_faculty_availability(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> AvailabilityResponse:
    """
    Return all unavailability slots for a faculty member.

    200 OK — always (no role check on reads — returns empty if no slots).
    """
    slots = await availability_service.get_faculty_slots(db=db, user_id=user_id)
    return _to_response(user_id=user_id, slots=slots)


@router.put(
    "/faculty/{user_id}",
    response_model=AvailabilityResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace faculty availability",
    description=(
        "Admin-only. Atomically replace ALL unavailability slots for a faculty member. "
        "The user must have role=FACULTY and be active. "
        "Sends the COMPLETE new set of blocked slots. "
        "An empty slots list [] clears all unavailability. "
        "Duplicate (day, slot_hour) pairs are silently de-duplicated."
    ),
    operation_id="replace_faculty_availability",
)
async def replace_faculty_availability(
    user_id: uuid.UUID,
    body: FacultyAvailabilityCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> AvailabilityResponse:
    """
    Bulk-replace faculty availability.

    200 OK       — replaced successfully. Returns the new full set.
    400 Bad Request — user_id references a non-FACULTY user.
    404 Not Found   — user_id not found or user is deactivated.
    """
    try:
        slots = await availability_service.replace_faculty_slots(
            db=db,
            user_id=user_id,
            slots=body.slots,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return _to_response(user_id=user_id, slots=slots)


@router.post(
    "/faculty/{user_id}/slots",
    response_model=AvailabilitySlotRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add one faculty unavailability slot",
    description=(
        "Admin-only. Add a single unavailability slot for a faculty member. "
        "Use PUT /{user_id} to replace the entire set at once."
    ),
    operation_id="add_faculty_slot",
)
async def add_faculty_slot(
    user_id: uuid.UUID,
    body: SlotInput,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> AvailabilitySlotRead:
    """
    Add one slot to faculty unavailability.

    201 Created  — slot added.
    400 Bad Request — user_id is not a FACULTY user.
    404 Not Found   — user_id not found or deactivated.
    409 Conflict    — this (day, slot_hour) is already blocked.
    """
    try:
        slot = await availability_service.add_faculty_slot(
            db=db,
            user_id=user_id,
            slot=body,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return AvailabilitySlotRead.model_validate(slot)


@router.delete(
    "/faculty/{user_id}/slots/{slot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one faculty unavailability slot",
    description=(
        "Admin-only. Remove a single unavailability slot by its UUID. "
        "The slot must belong to the specified user_id."
    ),
    operation_id="delete_faculty_slot",
)
async def delete_faculty_slot(
    user_id: uuid.UUID,
    slot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    """
    Delete one faculty availability slot.

    204 No Content — slot deleted.
    404 Not Found  — slot not found, or does not belong to this user.
    """
    try:
        await availability_service.delete_faculty_slot(
            db=db,
            user_id=user_id,
            slot_id=slot_id,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)


# ═══════════════════════════════════════════════════════════════════════════════
# TA Availability endpoints (identical shape to Faculty)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/ta/{user_id}",
    response_model=AvailabilityResponse,
    status_code=status.HTTP_200_OK,
    summary="Get TA availability",
    description=(
        "Admin-only. Return all unavailability slots for a TA. "
        "Returns an empty list if the TA has no blocked slots."
    ),
    operation_id="get_ta_availability",
)
async def get_ta_availability(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> AvailabilityResponse:
    """
    Return all unavailability slots for a TA.

    200 OK — always.
    """
    slots = await availability_service.get_ta_slots(db=db, user_id=user_id)
    return _to_response(user_id=user_id, slots=slots)


@router.put(
    "/ta/{user_id}",
    response_model=AvailabilityResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace TA availability",
    description=(
        "Admin-only. Atomically replace ALL unavailability slots for a TA. "
        "The user must have role=TA and be active. "
        "Sends the COMPLETE new set of blocked slots. "
        "An empty slots list [] clears all unavailability. "
        "Duplicate (day, slot_hour) pairs are silently de-duplicated."
    ),
    operation_id="replace_ta_availability",
)
async def replace_ta_availability(
    user_id: uuid.UUID,
    body: TAAvailabilityCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> AvailabilityResponse:
    """
    Bulk-replace TA availability.

    200 OK       — replaced successfully. Returns the new full set.
    400 Bad Request — user_id references a non-TA user.
    404 Not Found   — user_id not found or deactivated.
    """
    try:
        slots = await availability_service.replace_ta_slots(
            db=db,
            user_id=user_id,
            slots=body.slots,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return _to_response(user_id=user_id, slots=slots)


@router.post(
    "/ta/{user_id}/slots",
    response_model=AvailabilitySlotRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add one TA unavailability slot",
    description=(
        "Admin-only. Add a single unavailability slot for a TA. "
        "Use PUT /{user_id} to replace the entire set at once."
    ),
    operation_id="add_ta_slot",
)
async def add_ta_slot(
    user_id: uuid.UUID,
    body: SlotInput,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> AvailabilitySlotRead:
    """
    Add one slot to TA unavailability.

    201 Created  — slot added.
    400 Bad Request — user_id is not a TA user.
    404 Not Found   — user_id not found or deactivated.
    409 Conflict    — this (day, slot_hour) is already blocked.
    """
    try:
        slot = await availability_service.add_ta_slot(
            db=db,
            user_id=user_id,
            slot=body,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return AvailabilitySlotRead.model_validate(slot)


@router.delete(
    "/ta/{user_id}/slots/{slot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one TA unavailability slot",
    description=(
        "Admin-only. Remove a single TA unavailability slot by its UUID. "
        "The slot must belong to the specified user_id."
    ),
    operation_id="delete_ta_slot",
)
async def delete_ta_slot(
    user_id: uuid.UUID,
    slot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    """
    Delete one TA availability slot.

    204 No Content — slot deleted.
    404 Not Found  — slot not found, or does not belong to this user.
    """
    try:
        await availability_service.delete_ta_slot(
            db=db,
            user_id=user_id,
            slot_id=slot_id,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)
