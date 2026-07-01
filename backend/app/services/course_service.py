"""
services/course_service.py — Business logic for Course Management.

Responsibilities:
  - Create courses (semester existence check + (semester_id, code) uniqueness).
  - List courses for a semester (ordered by tier ASC, name ASC).
  - Get a single course by UUID.
  - Update course name, code, and/or tier (partial, via model_fields_set).
  - Delete a course (CASCADE — no FK guard needed; assignments and timetable
    entries are removed automatically by the DB).

Design principles:
  - NO HTTP knowledge.  No FastAPI, no HTTPException, no status codes.
    Business-rule violations raise plain ValueError.  The route layer
    (api/courses.py) converts these to HTTP responses.
  - Every function is async and receives an AsyncSession from DI.
  - SQLAlchemy 2.0 select() / func.count() API throughout.
  - db.flush() after writes, never db.commit() — the route layer commits.

Uniqueness constraint:
  The DB enforces uq_courses_semester_code: no two courses in the same
  semester may share the same code.  We pre-check with a SELECT before
  INSERT/UPDATE to produce a clean 409 error rather than catching an
  IntegrityError (which gives a less readable message).

Why pre-check here (vs. the TOCTOU-catch pattern used for RESTRICT FKs)?
  The TOCTOU risk is negligible for CREATE/UPDATE uniqueness checks in
  this application context: concurrent admins creating the same course
  code in the same semester is not a realistic concurrent write scenario.
  Pre-checking gives cleaner, more specific error messages.  The DB
  constraint remains the authoritative safety net for the rare race.

Ordering for list_courses:
  tier ASC, name ASC mirrors the scheduler's context.py priority: higher
  tiers (TIER_1 = 4-credit, most constrained) are processed first, and
  within a tier courses are alphabetically stable.  This makes the admin
  list directly correspond to the scheduler's processing order.

Delete:
  course_assignments.course_id has ON DELETE CASCADE (fk_ca_course_id).
  timetable_entries.assignment_id has ON DELETE CASCADE (fk_te_assignment_id).
  Deleting a course cleanly cascades to all downstream data.
  No IntegrityError will be raised; no try/except needed.

Error contract:
  get_course_by_id  → None if not found (route returns 404)
  create_course     → ValueError("Semester not found.")
                   → ValueError("Course code '...' already exists in this semester.")
  update_course     → ValueError("Course not found.")
                   → ValueError("Course code '...' already exists in this semester.")
  delete_course     → ValueError("Course not found.")
  list_courses      → always succeeds (returns empty list if no courses)
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.semester import Semester
from app.schemas.course import CourseCreate, CourseUpdate


# ── Read helpers ──────────────────────────────────────────────────────────────

async def get_course_by_id(
    db: AsyncSession,
    course_id: uuid.UUID,
) -> Course | None:
    """
    Return the Course with the given UUID, or None if not found.

    Uses db.get() for identity-map cache benefit.
    """
    return await db.get(Course, course_id)


async def get_course_by_semester_and_code(
    db: AsyncSession,
    semester_id: uuid.UUID,
    code: str,
) -> Course | None:
    """
    Return the Course matching (semester_id, code), or None.

    Used internally for the composite uniqueness check on
    uq_courses_semester_code during create and update.
    """
    result = await db.execute(
        select(Course).where(
            Course.semester_id == semester_id,
            Course.code == code,
        )
    )
    return result.scalars().first()


async def list_courses(
    db: AsyncSession,
    semester_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
) -> tuple[int, list[Course]]:
    """
    Return a (total_count, page_of_courses) tuple for a given semester.

    Args:
      db:          Async DB session.
      semester_id: Filter — only courses in this semester are returned.
                   This is always required; courses are meaningless without
                   semester context.
      skip:        Offset for pagination.
      limit:       Max rows per page (capped at 200 by the route).

    Ordering: tier ASC, name ASC.
      - tier ASC: TIER_1 (4-credit, most constrained) first, matching the
        scheduler's processing priority documented in context.py.
      - name ASC: stable alphabetical ordering within each tier.

    Returns:
      (total_count_before_pagination, list_of_Course_objects)
    """
    base_filter = [Course.semester_id == semester_id]

    count_result = await db.execute(
        select(func.count()).select_from(Course).where(*base_filter)
    )
    total: int = count_result.scalar_one()

    data_result = await db.execute(
        select(Course)
        .where(*base_filter)
        .order_by(Course.tier.asc(), Course.name.asc())
        .offset(skip)
        .limit(limit)
    )
    courses = list(data_result.scalars().all())

    return total, courses


# ── Mutations ─────────────────────────────────────────────────────────────────

async def create_course(
    db: AsyncSession,
    data: CourseCreate,
) -> Course:
    """
    Create a new course in a semester.

    Steps:
      1. Verify the semester exists (prevents orphaned courses and gives a
         clear 404 rather than a FK violation from the DB).
      2. Check that (semester_id, code) is unique within the semester.
         CourseCreate.normalise_code already uppercased the code, matching
         the stored values which were also uppercased at creation.
      3. Create the Course ORM object and flush().

    Raises:
      ValueError("Semester not found.")                — semester_id invalid.
      ValueError("Course code '...' already exists …") — code conflict.
    """
    # Step 1: verify semester exists
    semester = await db.get(Semester, data.semester_id)
    if semester is None:
        raise ValueError(f"Semester {data.semester_id} not found.")

    # Step 2: (semester_id, code) uniqueness
    conflict = await get_course_by_semester_and_code(
        db=db,
        semester_id=data.semester_id,
        code=data.code,
    )
    if conflict is not None:
        raise ValueError(
            f"Course code '{data.code}' already exists in this semester."
        )

    course = Course(
        semester_id=data.semester_id,
        name=data.name,
        code=data.code,
        tier=data.tier,
    )

    db.add(course)
    await db.flush()
    await db.refresh(course)
    return course


async def update_course(
    db: AsyncSession,
    course_id: uuid.UUID,
    data: CourseUpdate,
) -> Course:
    """
    Partially update a course's name, code, and/or tier.

    Uses model_fields_set for PATCH semantics — omitted fields unchanged.
    An empty body {} is a valid no-op.

    If `code` is changed, the new (semester_id, code) pair is checked for
    uniqueness within the course's current semester.

    semester_id is intentionally NOT updatable — see module docstring.

    Raises:
      ValueError("Course not found.")
      ValueError("Course code '...' already exists in this semester.")
    """
    course = await get_course_by_id(db=db, course_id=course_id)
    if course is None:
        raise ValueError("Course not found.")

    if "name" in data.model_fields_set and data.name is not None:
        course.name = data.name

    if "code" in data.model_fields_set and data.code is not None:
        # Only check uniqueness when the code is actually changing
        if data.code != course.code:
            conflict = await get_course_by_semester_and_code(
                db=db,
                semester_id=course.semester_id,
                code=data.code,
            )
            if conflict is not None:
                raise ValueError(
                    f"Course code '{data.code}' already exists in this semester."
                )
        course.code = data.code

    if "tier" in data.model_fields_set and data.tier is not None:
        course.tier = data.tier

    await db.flush()
    await db.refresh(course)
    return course


async def delete_course(
    db: AsyncSession,
    course_id: uuid.UUID,
) -> None:
    """
    Hard-delete a course.

    Cascade behaviour (confirmed in migration):
      course_assignments.course_id → ON DELETE CASCADE (fk_ca_course_id)
      timetable_entries.assignment_id → ON DELETE CASCADE (fk_te_assignment_id)

    Deleting a course cleanly removes all associated assignments and
    timetable entries.  No IntegrityError will be raised.
    No try/except needed — the cascade is silent and complete.

    Raises:
      ValueError("Course not found.") — if course_id doesn't exist.
    """
    course = await get_course_by_id(db=db, course_id=course_id)
    if course is None:
        raise ValueError("Course not found.")

    await db.delete(course)
    await db.flush()
