"""
api/rooms.py — Admin-only Room Management endpoints.

All endpoints require role = ADMIN (enforced via Depends(require_admin)).

Endpoint map:

  POST   /api/v1/rooms                  Create a room
  GET    /api/v1/rooms                  List rooms (with optional ?room_type= filter)
  GET    /api/v1/rooms/{room_id}        Get a single room by UUID
  PATCH  /api/v1/rooms/{room_id}        Update room name / type / capacity
  DELETE /api/v1/rooms/{room_id}        Delete a room (hard delete)

Design principles:
  - Thin routes: validate → call service → return schema.
  - ValueError → HTTP status via _handle_value_error helper.
  - Every mutating route wraps in try/commit + except/rollback.
  - All endpoints have unique operation_id for OpenAPI client generation.

Notes on the room lifecycle:
  - CREATE: Admin provides name, room_type, and capacity.  All three fields
    are stored directly (no derivation, unlike sections).
  - UPDATE: All fields are updatable via PATCH.  Name gets a uniqueness
    re-check; room_type and capacity are free to change.
  - DELETE: Blocked by RESTRICT FK if live timetable entries reference the
    room.  Service translates IntegrityError → ValueError → 409 Conflict.
  - LIST: Supports optional ?room_type=LECTURE_HALL or ?room_type=LAB filter.
    Ordered by room_type ASC, capacity ASC (mirrors scheduler's best-fit index).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.models.enums import RoomType
from app.models.user import User
from app.schemas.room import RoomCreate, RoomRead, RoomUpdate
from app.services import room_service

router = APIRouter(
    prefix="/rooms",
    tags=["rooms"],
)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _handle_value_error(exc: ValueError) -> HTTPException:
    """
    Convert a service-layer ValueError to the appropriate HTTPException.

    Mapping:
      message contains "not found"     → 404 Not Found
      message contains "already taken" → 409 Conflict
      message contains "cannot delete" → 409 Conflict
      anything else                    → 400 Bad Request
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


# ── POST /rooms — Create ──────────────────────────────────────────────────────

@router.post(
    "",
    response_model=RoomRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create room",
    description=(
        "Admin-only. Create a new room. "
        "room_type must be 'LECTURE_HALL' (for lectures and tutorials) "
        "or 'LAB' (for lab sessions only). "
        "capacity must be greater than 0."
    ),
    operation_id="create_room",
)
async def create_room(
    body: RoomCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> RoomRead:
    """
    Create a room.

    201 Created  — room created.
    409 Conflict — name is already taken.
    422 Unprocessable — room_type not LECTURE_HALL/LAB, capacity ≤ 0.
    """
    try:
        room = await room_service.create_room(db=db, data=body)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return RoomRead.model_validate(room)


# ── GET /rooms — List rooms ───────────────────────────────────────────────────

@router.get(
    "",
    response_model=list[RoomRead],
    status_code=status.HTTP_200_OK,
    summary="List rooms",
    description=(
        "Admin-only. Return all rooms ordered by type then capacity. "
        "Filter by type with ?room_type=LECTURE_HALL or ?room_type=LAB. "
        "No pagination — rooms are a small, bounded set."
    ),
    operation_id="list_rooms",
)
async def list_rooms(
    room_type: RoomType | None = Query(
        default=None,
        description="Filter by room type. Omit to return all rooms.",
    ),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[RoomRead]:
    """
    Return all rooms, optionally filtered by type.

    200 OK — always (empty list if no rooms exist yet).
    """
    rooms = await room_service.list_rooms(db=db, room_type=room_type)
    return [RoomRead.model_validate(r) for r in rooms]


# ── GET /rooms/{room_id} — Get single ────────────────────────────────────────

@router.get(
    "/{room_id}",
    response_model=RoomRead,
    status_code=status.HTTP_200_OK,
    summary="Get room",
    description="Admin-only. Return a single room by UUID.",
    operation_id="get_room",
)
async def get_room(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> RoomRead:
    """
    Return a single room by UUID.

    200 OK        — room found.
    404 Not Found — no room with that UUID.
    """
    room = await room_service.get_room_by_id(db=db, room_id=room_id)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room {room_id} not found.",
        )
    return RoomRead.model_validate(room)


# ── PATCH /rooms/{room_id} — Update ──────────────────────────────────────────

@router.patch(
    "/{room_id}",
    response_model=RoomRead,
    status_code=status.HTTP_200_OK,
    summary="Update room",
    description=(
        "Admin-only. Partially update a room's name, type, and/or capacity. "
        "Only explicitly provided fields are updated. "
        "An empty body {} is a valid no-op."
    ),
    operation_id="update_room",
)
async def update_room(
    room_id: uuid.UUID,
    body: RoomUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> RoomRead:
    """
    Partially update a room.

    200 OK        — update applied (or no-op if body was empty).
    404 Not Found — no room with that UUID.
    409 Conflict  — new name is already taken by another room.
    422 Unprocessable — capacity ≤ 0, invalid room_type.
    """
    try:
        room = await room_service.update_room(
            db=db,
            room_id=room_id,
            data=body,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)

    return RoomRead.model_validate(room)


# ── DELETE /rooms/{room_id} — Hard delete ─────────────────────────────────────

@router.delete(
    "/{room_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete room",
    description=(
        "Admin-only. Permanently delete a room. "
        "Blocked if any timetable entries reference this room "
        "(ON DELETE RESTRICT). "
        "Delete or regenerate the timetable first."
    ),
    operation_id="delete_room",
)
async def delete_room(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    """
    Hard-delete a room.

    204 No Content — room deleted.
    404 Not Found  — no room with that UUID.
    409 Conflict   — live timetable entries exist (RESTRICT FK).
    """
    try:
        await room_service.delete_room(db=db, room_id=room_id)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise _handle_value_error(exc)
