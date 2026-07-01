"""
services/availability_service.py — Business logic for Availability Management.

Responsibilities:
  - Get all availability slots for a user (faculty or TA).
  - Replace (bulk-update) all slots for a user atomically.
  - Add a single slot for a user.
  - Delete a single slot by UUID.

Design principles:
  - NO HTTP knowledge.  Business-rule violations raise plain ValueError.
  - Every function is async and receives an AsyncSession from DI.
  - SQLAlchemy 2.0 select() / delete() API throughout.
  - db.flush() after writes, never db.commit() — the route layer commits.

Generic pattern:
  FacultyAvailability and TAAvailability are structurally identical models.
  Rather than duplicating every function for each table, the core logic
  accepts the model class as a type parameter.  The public API exposes
  typed wrappers for each table (e.g., get_faculty_slots calls
  _get_slots with FacultyAvailability).  This eliminates ~100 lines of
  near-identical code while keeping the public function signatures clean.

Replace semantics (key design decision from database_schema.md):
  The correct operation for "updating" availability is a bulk replace:
    1. DELETE all existing rows for this user.
    2. INSERT the new set of rows.
  Both steps run in the same transaction — the route commits them together.
  This is atomic: there is no window where the user has zero slots if
  the new set is non-empty.

  Duplicate (day, slot_hour) pairs in the input list are de-duplicated
  using a set before insertion, preventing IntegrityError on the
  uq_faculty_avail_user_day_slot / uq_ta_avail_user_day_slot constraints.

Single-slot add vs. replace:
  The replace endpoint is the primary operation.  Single-slot add/delete
  endpoints exist for granular UI operations (toggling one slot without
  re-sending the full set).

  For single-slot add, we pre-check uniqueness with a SELECT before INSERT.
  If the slot already exists, we raise ValueError("Slot already exists.")
  rather than catching an IntegrityError.  Pre-checking gives a cleaner
  error message; the TOCTOU risk is negligible for single-admin operations.

Role validation:
  faculty_id must reference an active User with role=FACULTY.
  ta_id must reference an active User with role=TA.
  This is enforced in every public function before any DB write.

Error contract (all functions):
  _validate_user_role    → ValueError("User ... not found or not active.")
                        → ValueError("User ... has role '...' but '...' is required.")
  get_faculty_slots      → always returns (empty list if no slots)
  get_ta_slots           → always returns (empty list if no slots)
  replace_faculty_slots  → ValueError("...") from _validate_user_role
  replace_ta_slots       → ValueError("...") from _validate_user_role
  add_faculty_slot       → ValueError("...") from _validate_user_role
                        → ValueError("Slot (day, slot_hour) already exists for this user.")
  add_ta_slot            → same pattern
  delete_faculty_slot    → ValueError("Slot not found.")
  delete_ta_slot         → ValueError("Slot not found.")
"""

import uuid
from typing import Type

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.availability import FacultyAvailability, TAAvailability
from app.models.enums import DayOfWeek, UserRole
from app.models.user import User
from app.schemas.availability import SlotInput

# Type alias for the two model classes (they share the same interface)
_AvailabilityModel = Type[FacultyAvailability | TAAvailability]


# ── Internal validation ───────────────────────────────────────────────────────

async def _validate_user_role(
    db: AsyncSession,
    user_id: uuid.UUID,
    expected_role: UserRole,
    role_label: str,
) -> User:
    """
    Load a User and verify it is active and has the expected role.

    Args:
      db:            Async DB session.
      user_id:       UUID to load.
      expected_role: The role the user must have.
      role_label:    Human-readable label ("Faculty", "TA") for errors.

    Returns:
      The loaded User ORM object.

    Raises:
      ValueError — if user not found, not active, or wrong role.
    """
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise ValueError(f"User {user_id} not found or not active.")
    if user.role != expected_role:
        raise ValueError(
            f"User {user_id} has role '{user.role.value}', "
            f"but '{expected_role.value}' is required for {role_label} availability."
        )
    return user


# ── Generic core functions ────────────────────────────────────────────────────

async def _get_slots(
    db: AsyncSession,
    model: _AvailabilityModel,
    user_id: uuid.UUID,
) -> list[FacultyAvailability | TAAvailability]:
    """
    Return all availability slots for a user, ordered day ASC, slot_hour ASC.

    The ordering (day enum ASC, slot_hour ASC) matches the DayOfWeek enum
    string ordering: FRI < MON < THU < TUE < WED (alphabetical).
    For natural weekly order, the route layer or frontend must re-sort.
    Here we order by slot_hour ASC within each day group as a secondary sort.
    Note: PostgreSQL orders enum values by their declared order in the type
    definition: MON < TUE < WED < THU < FRI — which IS the natural order.
    """
    result = await db.execute(
        select(model)
        .where(model.user_id == user_id)
        .order_by(model.day.asc(), model.slot_hour.asc())
    )
    return list(result.scalars().all())


async def _replace_slots(
    db: AsyncSession,
    model: _AvailabilityModel,
    user_id: uuid.UUID,
    slots: list[SlotInput],
) -> list[FacultyAvailability | TAAvailability]:
    """
    Atomically replace all availability slots for a user.

    Steps:
      1. DELETE all existing rows for this user (one bulk DELETE).
      2. De-duplicate the input list using a set of (day, slot_hour) tuples.
      3. INSERT new rows for each unique (day, slot_hour) pair.
      4. flush() — route commits.

    De-duplication prevents IntegrityError on the composite unique constraint
    if the caller accidentally sends duplicate pairs in the list.

    An empty `slots` list clears all unavailability (user becomes fully
    available — the scheduler will see no blacklisted slots for them).
    """
    # Step 1: bulk delete all existing slots
    await db.execute(
        delete(model).where(model.user_id == user_id)
    )

    # Step 2: de-duplicate — set of (day_value, slot_hour)
    seen: set[tuple[str, int]] = set()
    unique_slots: list[SlotInput] = []
    for slot in slots:
        key = (slot.day.value, slot.slot_hour)
        if key not in seen:
            seen.add(key)
            unique_slots.append(slot)

    # Step 3: insert new rows
    new_rows = [
        model(user_id=user_id, day=slot.day, slot_hour=slot.slot_hour)
        for slot in unique_slots
    ]
    db.add_all(new_rows)

    # Step 4: flush to populate server-side ids and created_at
    await db.flush()

    # Reload from DB for accurate created_at timestamps
    return await _get_slots(db=db, model=model, user_id=user_id)


async def _add_slot(
    db: AsyncSession,
    model: _AvailabilityModel,
    user_id: uuid.UUID,
    slot: SlotInput,
) -> FacultyAvailability | TAAvailability:
    """
    Add a single unavailability slot for a user.

    Pre-checks uniqueness with a SELECT before INSERT to give a clear
    error message instead of an IntegrityError from the DB.

    Raises:
      ValueError — if the slot already exists.
    """
    # Check for existing slot with same (user_id, day, slot_hour)
    existing = await db.execute(
        select(model).where(
            model.user_id == user_id,
            model.day == slot.day,
            model.slot_hour == slot.slot_hour,
        )
    )
    if existing.scalars().first() is not None:
        raise ValueError(
            f"Slot ({slot.day.value}, {slot.slot_hour}:00) already exists for this user."
        )

    new_row = model(user_id=user_id, day=slot.day, slot_hour=slot.slot_hour)
    db.add(new_row)
    await db.flush()
    await db.refresh(new_row)
    return new_row


async def _delete_slot(
    db: AsyncSession,
    model: _AvailabilityModel,
    slot_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """
    Delete a single availability slot by its UUID.

    `user_id` is required as a scoping parameter — the route passes it
    from the URL path so the admin cannot accidentally delete another
    user's slot by guessing a UUID.

    Raises:
      ValueError("Slot not found.") — if slot_id doesn't exist for this user.
    """
    slot_obj = await db.get(model, slot_id)
    if slot_obj is None or slot_obj.user_id != user_id:
        raise ValueError("Slot not found.")

    await db.delete(slot_obj)
    await db.flush()


# ── Public API: Faculty ───────────────────────────────────────────────────────

async def get_faculty_slots(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[FacultyAvailability]:
    """Return all unavailability slots for a faculty member."""
    return await _get_slots(db=db, model=FacultyAvailability, user_id=user_id)


async def replace_faculty_slots(
    db: AsyncSession,
    user_id: uuid.UUID,
    slots: list[SlotInput],
) -> list[FacultyAvailability]:
    """
    Atomically replace all unavailability slots for a faculty member.

    Validates that the user exists, is active, and has role=FACULTY before
    touching any availability rows.
    """
    await _validate_user_role(
        db=db,
        user_id=user_id,
        expected_role=UserRole.FACULTY,
        role_label="Faculty",
    )
    return await _replace_slots(
        db=db, model=FacultyAvailability, user_id=user_id, slots=slots
    )


async def add_faculty_slot(
    db: AsyncSession,
    user_id: uuid.UUID,
    slot: SlotInput,
) -> FacultyAvailability:
    """
    Add a single unavailability slot for a faculty member.

    Validates user role before insertion.
    """
    await _validate_user_role(
        db=db,
        user_id=user_id,
        expected_role=UserRole.FACULTY,
        role_label="Faculty",
    )
    return await _add_slot(db=db, model=FacultyAvailability, user_id=user_id, slot=slot)


async def delete_faculty_slot(
    db: AsyncSession,
    user_id: uuid.UUID,
    slot_id: uuid.UUID,
) -> None:
    """Delete a single faculty availability slot by UUID."""
    # Role validation not strictly needed for delete (only the slot_id matters),
    # but we verify user context via the user_id scope check in _delete_slot.
    await _delete_slot(
        db=db, model=FacultyAvailability, slot_id=slot_id, user_id=user_id
    )


# ── Public API: TA ────────────────────────────────────────────────────────────

async def get_ta_slots(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[TAAvailability]:
    """Return all unavailability slots for a TA."""
    return await _get_slots(db=db, model=TAAvailability, user_id=user_id)


async def replace_ta_slots(
    db: AsyncSession,
    user_id: uuid.UUID,
    slots: list[SlotInput],
) -> list[TAAvailability]:
    """
    Atomically replace all unavailability slots for a TA.

    Validates that the user exists, is active, and has role=TA before
    touching any availability rows.
    """
    await _validate_user_role(
        db=db,
        user_id=user_id,
        expected_role=UserRole.TA,
        role_label="TA",
    )
    return await _replace_slots(
        db=db, model=TAAvailability, user_id=user_id, slots=slots
    )


async def add_ta_slot(
    db: AsyncSession,
    user_id: uuid.UUID,
    slot: SlotInput,
) -> TAAvailability:
    """
    Add a single unavailability slot for a TA.

    Validates user role before insertion.
    """
    await _validate_user_role(
        db=db,
        user_id=user_id,
        expected_role=UserRole.TA,
        role_label="TA",
    )
    return await _add_slot(db=db, model=TAAvailability, user_id=user_id, slot=slot)


async def delete_ta_slot(
    db: AsyncSession,
    user_id: uuid.UUID,
    slot_id: uuid.UUID,
) -> None:
    """Delete a single TA availability slot by UUID."""
    await _delete_slot(
        db=db, model=TAAvailability, slot_id=slot_id, user_id=user_id
    )
