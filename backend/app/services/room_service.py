"""
services/room_service.py — Business logic for Room Management.

Responsibilities:
  - Create rooms (with name-uniqueness check).
  - List rooms (with optional room_type filter, ordered by type then capacity).
  - Get a single room by UUID.
  - Update room fields: name, room_type, capacity (partial via model_fields_set).
  - Delete a room (guarded by RESTRICT FK on timetable_entries.room_id).

Design principles:
  - NO HTTP knowledge.  No FastAPI, no HTTPException, no status codes.
    Business-rule violations raise plain ValueError.  The route layer
    (api/rooms.py) converts these to HTTP responses.
  - Every function is async and receives an AsyncSession from DI.
  - SQLAlchemy 2.0 select() API throughout.
  - db.flush() after writes, never db.commit() — the route layer commits.

List ordering:
  ORDER BY room_type ASC, capacity ASC mirrors the scheduler's best-fit
  index (idx_rooms_type_capacity).  LECTURE_HALLs come before LABs (L < L
  alphabetically), and within each type rooms are sorted smallest-first.
  This natural order makes the admin list directly readable: all lecture
  halls in ascending capacity, then all labs in ascending capacity.

Delete guard:
  timetable_entries.room_id has ON DELETE RESTRICT (confirmed in migration
  line 686: fk_te_room_id).  Deleting a room referenced by live timetable
  entries raises an IntegrityError from PostgreSQL.  We catch it and
  re-raise as ValueError — the route returns 409 Conflict.
  We do NOT pre-check — that would be a TOCTOU race.  The DB is the
  authoritative enforcer.

Error contract:
  get_room_by_id → None if not found (route returns 404)
  create_room    → ValueError("Room name '...' is already taken.")
  update_room    → ValueError("Room not found.")
                → ValueError("Room name '...' is already taken.")
  delete_room    → ValueError("Room not found.")
               → ValueError("Cannot delete room '...' because it has live ...")
                  if the RESTRICT FK fires
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RoomType
from app.models.room import Room
from app.schemas.room import RoomCreate, RoomUpdate


# ── Read helpers ──────────────────────────────────────────────────────────────

async def get_room_by_id(
    db: AsyncSession,
    room_id: uuid.UUID,
) -> Room | None:
    """
    Return the Room with the given UUID, or None if not found.

    Uses db.get() for identity-map cache benefit — avoids a SELECT if the
    object was already loaded earlier in the same request lifecycle.
    """
    return await db.get(Room, room_id)


async def get_room_by_name(
    db: AsyncSession,
    name: str,
) -> Room | None:
    """
    Return the Room with the given name, or None if not found.

    Used internally for name-uniqueness checks during create and update.
    """
    result = await db.execute(
        select(Room).where(Room.name == name)
    )
    return result.scalars().first()


async def list_rooms(
    db: AsyncSession,
    room_type: RoomType | None = None,
) -> list[Room]:
    """
    Return all rooms, ordered by room_type ASC then capacity ASC.

    Args:
      db:        Async DB session.
      room_type: Optional filter.  If provided, only rooms of that type
                 are returned.  If None (default), all rooms are returned.

    Ordering: room_type ASC, capacity ASC — this mirrors the scheduler's
    best-fit index (idx_rooms_type_capacity) and groups the admin list
    naturally: all LECTURE_HALLs by increasing capacity, then all LABs.

    No pagination — the total number of rooms in scope is small and bounded.
    """
    filters = []
    if room_type is not None:
        filters.append(Room.room_type == room_type)

    result = await db.execute(
        select(Room)
        .where(*filters)
        .order_by(Room.room_type.asc(), Room.capacity.asc())
    )
    return list(result.scalars().all())


# ── Mutations ─────────────────────────────────────────────────────────────────

async def create_room(
    db: AsyncSession,
    data: RoomCreate,
) -> Room:
    """
    Create a new room.

    Steps:
      1. Check that the name is not already taken (name is UNIQUE in DB).
      2. Create the Room ORM object.
      3. flush() to populate server-side defaults (id, created_at, updated_at).

    Raises:
      ValueError("Room name '...' is already taken.") — if name conflicts.
    """
    existing = await get_room_by_name(db=db, name=data.name)
    if existing is not None:
        raise ValueError(f"Room name '{data.name}' is already taken.")

    room = Room(
        name=data.name,
        room_type=data.room_type,
        capacity=data.capacity,
    )

    db.add(room)
    await db.flush()
    await db.refresh(room)
    return room


async def update_room(
    db: AsyncSession,
    room_id: uuid.UUID,
    data: RoomUpdate,
) -> Room:
    """
    Partially update a room's name, room_type, and/or capacity.

    Uses model_fields_set for true PATCH semantics:
      - Fields not present in the request body are left unchanged.
      - An empty body {} is a valid no-op that returns the room unchanged.

    Name uniqueness is only re-checked when the name is explicitly provided
    AND it differs from the current value.  This prevents spurious 409s when
    an admin sends the same name in the body alongside a capacity change.

    Raises:
      ValueError("Room not found.")        — if room_id doesn't exist.
      ValueError("Room name '...' is already taken.") — if new name conflicts.
    """
    room = await get_room_by_id(db=db, room_id=room_id)
    if room is None:
        raise ValueError("Room not found.")

    if "name" in data.model_fields_set and data.name is not None:
        if data.name != room.name:
            conflict = await get_room_by_name(db=db, name=data.name)
            if conflict is not None:
                raise ValueError(f"Room name '{data.name}' is already taken.")
        room.name = data.name

    if "room_type" in data.model_fields_set and data.room_type is not None:
        room.room_type = data.room_type

    if "capacity" in data.model_fields_set and data.capacity is not None:
        room.capacity = data.capacity

    await db.flush()
    await db.refresh(room)
    return room


async def delete_room(
    db: AsyncSession,
    room_id: uuid.UUID,
) -> None:
    """
    Hard-delete a room.

    Guard:
      timetable_entries.room_id has ON DELETE RESTRICT (fk_te_room_id in
      the migration).  PostgreSQL raises an IntegrityError if any timetable
      entry references this room.  We catch it and re-raise as ValueError
      so the route returns 409 Conflict with a clear message.

    Pattern: do NOT pre-check with a COUNT — that is a TOCTOU race.
    Let the DB enforce the constraint and catch the error.

    After catching IntegrityError, db.rollback() resets the session to a
    clean state before re-raising, so the session remains usable.

    Raises:
      ValueError("Room not found.")
      ValueError("Cannot delete room '...' because it has live timetable entries.")
    """
    room = await get_room_by_id(db=db, room_id=room_id)
    if room is None:
        raise ValueError("Room not found.")

    try:
        await db.delete(room)
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ValueError(
            f"Cannot delete room '{room.name}' because it has live timetable entries. "
            "Delete or regenerate the timetable first."
        )
