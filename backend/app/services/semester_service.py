"""
services/semester_service.py — Business logic for Semester Management.

Responsibilities:
  - Create semesters (with name-uniqueness check).
  - List all semesters (ordered by name).
  - Get a single semester by UUID.
  - Update a semester's name (with uniqueness re-check).
  - Delete a semester (guarded: cannot delete the active semester).
  - Set a semester as active (atomically: deactivate all others first).

Design principles:
  - NO HTTP knowledge.  No FastAPI, no HTTPException, no status codes.
    All business-rule violations raise plain ValueError with a message.
    The route layer (api/semesters.py) converts these to HTTP responses.
  - Every function is async and receives an AsyncSession from DI.
  - SQLAlchemy 2.0 select() / update() API throughout.
  - db.flush() after writes to surface server-side defaults (id,
    created_at, updated_at).  db.commit() is NOT called here — the
    route layer commits, keeping transaction control at the API boundary.

The set_active operation deserves special attention:
  The database schema note says: "Only one semester should be is_active=TRUE
  at a time.  Enforced at the service layer (not a DB partial unique index)
  since toggling is an explicit admin action."

  Implementation: a single UPDATE ... WHERE is_active = TRUE AND id != target
  clears all other active semesters, then the target is set to TRUE.  Both
  writes happen in the same transaction so there is no window where zero or
  two semesters are active simultaneously.

Error contract:
  get_semester_by_id  → None if not found (route returns 404)
  create_semester     → ValueError("Name already taken.")
  update_semester     → ValueError("Semester not found.")
                     → ValueError("Name already taken.")
  delete_semester     → ValueError("Semester not found.")
                     → ValueError("Cannot delete the active semester. ...")
  set_active          → ValueError("Semester not found.")
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.semester import Semester
from app.schemas.semester import SemesterCreate, SemesterUpdate


# ── Read helpers ──────────────────────────────────────────────────────────────

async def get_semester_by_id(
    db: AsyncSession,
    semester_id: uuid.UUID,
) -> Semester | None:
    """
    Return the Semester with the given UUID, or None if not found.

    Uses db.get() for identity-map cache benefit (no extra SELECT if the
    object was already loaded earlier in the same request).
    """
    return await db.get(Semester, semester_id)


async def get_semester_by_name(
    db: AsyncSession,
    name: str,
) -> Semester | None:
    """
    Return the Semester with the given name, or None if not found.

    Used internally for name-uniqueness checks during create and update.
    """
    result = await db.execute(
        select(Semester).where(Semester.name == name)
    )
    return result.scalars().first()


async def get_active_semester(db: AsyncSession) -> Semester | None:
    """
    Return the currently active semester, or None if none is active.

    The frontend calls this on load to know which semester to display by
    default.  The scheduler uses it to know which semester to operate on.
    """
    result = await db.execute(
        select(Semester).where(Semester.is_active.is_(True))
    )
    return result.scalars().first()


async def list_semesters(db: AsyncSession) -> list[Semester]:
    """
    Return all semesters ordered by name ascending.

    No pagination — semesters are a small, bounded set.
    Name ordering gives a predictable, deterministic list (alphabetical).
    The active semester does NOT bubble to the top here; the frontend uses
    is_active=True to highlight it.
    """
    result = await db.execute(
        select(Semester).order_by(Semester.name.asc())
    )
    return list(result.scalars().all())


# ── Mutations ─────────────────────────────────────────────────────────────────

async def create_semester(
    db: AsyncSession,
    data: SemesterCreate,
) -> Semester:
    """
    Create a new semester.

    Steps:
      1. Check that the name is unique.
      2. Create the Semester ORM object (is_active defaults to False).
      3. flush() to populate server-side defaults.

    Raises:
      ValueError("Name already taken.") — if the name conflicts.
    """
    existing = await get_semester_by_name(db=db, name=data.name)
    if existing is not None:
        raise ValueError(f"Semester name '{data.name}' is already taken.")

    semester = Semester(
        name=data.name,
        is_active=False,   # new semesters start inactive; use set-active explicitly
    )

    db.add(semester)
    await db.flush()
    await db.refresh(semester)
    return semester


async def update_semester(
    db: AsyncSession,
    semester_id: uuid.UUID,
    data: SemesterUpdate,
) -> Semester:
    """
    Partially update a semester's name.

    Uses model_fields_set to skip fields that were not provided in the
    request body (PATCH semantics — omitted fields are unchanged).

    Raises:
      ValueError("Semester not found.")  — if semester_id doesn't exist.
      ValueError("Name already taken.")  — if the new name conflicts.
    """
    semester = await get_semester_by_id(db=db, semester_id=semester_id)
    if semester is None:
        raise ValueError("Semester not found.")

    if "name" in data.model_fields_set and data.name is not None:
        # Only check uniqueness when the name is actually changing
        if data.name != semester.name:
            conflict = await get_semester_by_name(db=db, name=data.name)
            if conflict is not None:
                raise ValueError(f"Semester name '{data.name}' is already taken.")
        semester.name = data.name

    await db.flush()
    await db.refresh(semester)
    return semester


async def delete_semester(
    db: AsyncSession,
    semester_id: uuid.UUID,
) -> None:
    """
    Hard-delete a semester and all its cascaded data.

    The database schema defines:
      semesters.id ← courses.semester_id  (CASCADE)
      semesters.id ← timetables.semester_id (CASCADE)

    Deleting a semester therefore deletes all associated courses,
    course_assignments, timetables, timetable_entries, and conflict_reports.
    This is intentional — a semester is a coherent data unit.

    Guard:
      The active semester cannot be deleted.  Deleting it while it is the
      operational context would leave the system in an undefined state.
      Admin must first deactivate (set another semester active, or unset the
      current one) before deleting.

    Raises:
      ValueError("Semester not found.")
      ValueError("Cannot delete the active semester. ...")
    """
    semester = await get_semester_by_id(db=db, semester_id=semester_id)
    if semester is None:
        raise ValueError("Semester not found.")

    if semester.is_active:
        raise ValueError(
            "Cannot delete the active semester. "
            "Set another semester as active first, then delete this one."
        )

    await db.delete(semester)
    await db.flush()


async def set_active(
    db: AsyncSession,
    semester_id: uuid.UUID,
) -> Semester:
    """
    Mark the given semester as active, deactivating all others.

    This is the most important business operation in the semester module.
    It must be atomic: no window where zero or two semesters are active.

    Implementation (two SQL statements in the same transaction):
      1. UPDATE semesters SET is_active = FALSE WHERE is_active = TRUE
         AND id != :target_id
         — clears all other active semesters.
      2. target.is_active = True; flush()
         — marks the target active.

    Both writes are flushed to the DB before commit.  The route layer calls
    db.commit() to make both changes permanent atomically.

    Idempotent: setting the already-active semester to active is a no-op
    (step 1 finds nothing to clear, step 2 sets True on True).

    Raises:
      ValueError("Semester not found.") — if semester_id doesn't exist.
    """
    semester = await get_semester_by_id(db=db, semester_id=semester_id)
    if semester is None:
        raise ValueError("Semester not found.")

    # Step 1: deactivate every OTHER currently-active semester in one UPDATE
    # Using a bulk UPDATE avoids loading all semester objects into memory.
    await db.execute(
        update(Semester)
        .where(Semester.is_active.is_(True), Semester.id != semester_id)
        .values(is_active=False)
        # synchronize_session="fetch" tells SQLAlchemy to refresh any already-
        # loaded Semester ORM objects in the current session so they reflect
        # the new is_active=False value.
        .execution_options(synchronize_session="fetch")
    )

    # Step 2: mark the target semester as active
    semester.is_active = True
    await db.flush()
    await db.refresh(semester)
    return semester


async def unset_active(
    db: AsyncSession,
    semester_id: uuid.UUID,
) -> Semester:
    """
    Deactivate a semester without activating any other.

    After this call, no semester will be active.  This is a valid state —
    it means the admin has not yet decided which semester to work on next.

    Idempotent: calling on an already-inactive semester is a no-op.

    Raises:
      ValueError("Semester not found.") — if semester_id doesn't exist.
    """
    semester = await get_semester_by_id(db=db, semester_id=semester_id)
    if semester is None:
        raise ValueError("Semester not found.")

    semester.is_active = False
    await db.flush()
    await db.refresh(semester)
    return semester
