"""
services/course_assignment_service.py — Business logic for Course Assignment.

Responsibilities:
  - Create assignments (full pre-validation: existence, roles, uniqueness).
  - List assignments (filterable by course_id, section_id, and/or faculty_id).
  - Get a single assignment by UUID.
  - Update faculty_id and/or ta_id.
  - Delete an assignment (CASCADE — timetable entries removed automatically).

Design principles:
  - NO HTTP knowledge.  No FastAPI, no HTTPException, no status codes.
    Business-rule violations raise plain ValueError.  The route layer
    (api/assignments.py) converts these to HTTP responses.
  - Every function is async and receives an AsyncSession from DI.
  - SQLAlchemy 2.0 select() API throughout.
  - db.flush() after writes, never db.commit() — the route layer commits.

The TA Tier Rule (Removed):
  Previously, TIER_1 and TIER_2 courses required a TA, and TIER_3 and TIER_4 
  courses prohibited TAs. This restriction has been completely removed.
  TAs are now optional across all course tiers. If a TA is assigned, they 
  will participate in the course's Tutorial and/or Lab sessions as scheduled.

Role validation:
  faculty_id must reference a User with role=FACULTY.
  ta_id (when provided) must reference a User with role=TA.
  Both must be is_active=True.
  These checks prevent scheduling errors caused by wrong-role assignments.

Delete:
  timetable_entries.assignment_id has ON DELETE CASCADE (fk_te_assignment_id).
  Deleting an assignment removes all its timetable entries automatically.
  No IntegrityError is raised; no try/except needed.

Error contract:
  get_assignment_by_id → None if not found (route returns 404)
  create_assignment    → ValueError("Course not found.")
                      → ValueError("Section not found.")
                      → ValueError("Faculty user not found or not active.")
                      → ValueError("Faculty user does not have role FACULTY.")
                      → ValueError("TA user not found or not active.")
                      → ValueError("TA user does not have role TA.")
                      → ValueError("This course is already assigned to this section.")
  update_assignment    → ValueError("Assignment not found.")
                      → ValueError("Faculty user not found or not active.")
                      → ValueError("Faculty user does not have role FACULTY.")
                      → ValueError("TA user not found or not active.")
                      → ValueError("TA user does not have role TA.")
  delete_assignment    → ValueError("Assignment not found.")
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.course_assignment import CourseAssignment
from app.models.enums import CourseTier, UserRole
from app.models.section import Section
from app.models.user import User
from app.schemas.course_assignment import AssignmentCreate, AssignmentUpdate


# ── Internal validation helpers ───────────────────────────────────────────────

async def _load_active_user_with_role(
    db: AsyncSession,
    user_id: uuid.UUID,
    expected_role: UserRole,
    role_label: str,
) -> User:
    """
    Load a User by UUID and validate it is active with the expected role.

    Args:
      db:            Async DB session.
      user_id:       UUID to look up.
      expected_role: The role the user must have.
      role_label:    Human-readable label ("Faculty", "TA") for error messages.

    Returns:
      The loaded User ORM object.

    Raises:
      ValueError — if user not found, not active, or has the wrong role.
    """
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise ValueError(f"{role_label} user {user_id} not found or not active.")
    if user.role != expected_role:
        raise ValueError(
            f"User {user_id} has role '{user.role.value}', "
            f"but '{expected_role.value}' is required for {role_label}."
        )
    return user


# ── Read helpers ──────────────────────────────────────────────────────────────

async def get_assignment_by_id(
    db: AsyncSession,
    assignment_id: uuid.UUID,
) -> CourseAssignment | None:
    """
    Return the CourseAssignment with the given UUID, or None if not found.

    Uses db.get() for identity-map cache benefit.
    """
    return await db.get(CourseAssignment, assignment_id)


async def get_assignment_by_course_and_section(
    db: AsyncSession,
    course_id: uuid.UUID,
    section_id: uuid.UUID,
) -> CourseAssignment | None:
    """
    Return the assignment matching (course_id, section_id), or None.

    Used internally for the composite uniqueness check before INSERT.
    Mirrors the DB constraint uq_course_assignments_course_section.
    """
    result = await db.execute(
        select(CourseAssignment).where(
            CourseAssignment.course_id == course_id,
            CourseAssignment.section_id == section_id,
        )
    )
    return result.scalars().first()


async def list_assignments(
    db: AsyncSession,
    course_id: uuid.UUID | None = None,
    section_id: uuid.UUID | None = None,
    faculty_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 100,
) -> tuple[int, list[CourseAssignment]]:
    """
    Return a (total_count, page_of_assignments) tuple.

    Args:
      db:         Async DB session.
      course_id:  Filter by course.  If None, not filtered.
      section_id: Filter by section. If None, not filtered.
      faculty_id: Filter by faculty. If None, not filtered.
      skip:       Offset for pagination.
      limit:      Max rows per page.

    Multiple filters are AND-ed together.  Ordering: created_at ASC
    (stable, deterministic, reflects assignment entry order).

    Returns:
      (total_count_before_pagination, list_of_CourseAssignment_objects)
    """
    filters = []
    if course_id is not None:
        filters.append(CourseAssignment.course_id == course_id)
    if section_id is not None:
        filters.append(CourseAssignment.section_id == section_id)
    if faculty_id is not None:
        filters.append(CourseAssignment.faculty_id == faculty_id)

    count_result = await db.execute(
        select(func.count())
        .select_from(CourseAssignment)
        .where(*filters)
    )
    total: int = count_result.scalar_one()

    data_result = await db.execute(
        select(CourseAssignment)
        .where(*filters)
        .order_by(CourseAssignment.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    assignments = list(data_result.scalars().all())

    return total, assignments


# ── Mutations ─────────────────────────────────────────────────────────────────

async def create_assignment(
    db: AsyncSession,
    data: AssignmentCreate,
) -> CourseAssignment:
    """
    Create a new course assignment.

    Validation steps (in order):
      1. Course exists              → loads the tier for rule checks.
      2. Section exists.
      3. Faculty exists, is active, has role=FACULTY.
      4. TA exists, is active, has role=TA (if ta_id provided).
      5. (course_id, section_id)   → unique (mirrors DB constraint).
      6. INSERT + flush.

    Raises:
      ValueError — see module-level error contract.
    """
    # Step 1: load course (to get the tier)
    course = await db.get(Course, data.course_id)
    if course is None:
        raise ValueError(f"Course {data.course_id} not found.")

    # Step 2: section exists
    section = await db.get(Section, data.section_id)
    if section is None:
        raise ValueError(f"Section {data.section_id} not found.")

    # Step 3: faculty — must exist, be active, and have role=FACULTY
    await _load_active_user_with_role(
        db=db,
        user_id=data.faculty_id,
        expected_role=UserRole.FACULTY,
        role_label="Faculty",
    )

    # Step 4: TA — validate if provided
    if data.ta_id is not None:
        await _load_active_user_with_role(
            db=db,
            user_id=data.ta_id,
            expected_role=UserRole.TA,
            role_label="TA",
        )

    # Step 5: uniqueness check
    conflict = await get_assignment_by_course_and_section(
        db=db,
        course_id=data.course_id,
        section_id=data.section_id,
    )
    if conflict is not None:
        raise ValueError(
            f"This course is already assigned to this section "
            f"(assignment id: {conflict.id})."
        )

    # Step 6: create
    assignment = CourseAssignment(
        course_id=data.course_id,
        section_id=data.section_id,
        faculty_id=data.faculty_id,
        ta_id=data.ta_id,
    )

    db.add(assignment)
    await db.flush()
    await db.refresh(assignment)
    return assignment


async def update_assignment(
    db: AsyncSession,
    assignment_id: uuid.UUID,
    data: AssignmentUpdate,
) -> CourseAssignment:
    """
    Partially update an assignment's faculty and/or TA.

    Uses model_fields_set for PATCH semantics:
      - A field NOT in model_fields_set was not sent in the body → no change.
      - A field IN model_fields_set with value None means "set to None".

    Raises:
      ValueError — see module-level error contract.
    """
    assignment = await get_assignment_by_id(db=db, assignment_id=assignment_id)
    if assignment is None:
        raise ValueError("Assignment not found.")

    if "faculty_id" in data.model_fields_set and data.faculty_id is not None:
        await _load_active_user_with_role(
            db=db,
            user_id=data.faculty_id,
            expected_role=UserRole.FACULTY,
            role_label="Faculty",
        )
        assignment.faculty_id = data.faculty_id

    if "ta_id" in data.model_fields_set:
        if data.ta_id is not None:
            await _load_active_user_with_role(
                db=db,
                user_id=data.ta_id,
                expected_role=UserRole.TA,
                role_label="TA",
            )
        assignment.ta_id = data.ta_id

    await db.flush()
    await db.refresh(assignment)
    return assignment


async def delete_assignment(
    db: AsyncSession,
    assignment_id: uuid.UUID,
) -> None:
    """
    Hard-delete a course assignment.

    Cascade behaviour (confirmed in migration):
      timetable_entries.assignment_id → ON DELETE CASCADE (fk_te_assignment_id)

    Deleting an assignment removes all its timetable entries automatically.
    No IntegrityError will be raised; no try/except needed.

    Raises:
      ValueError("Assignment not found.") — if assignment_id doesn't exist.
    """
    assignment = await get_assignment_by_id(db=db, assignment_id=assignment_id)
    if assignment is None:
        raise ValueError("Assignment not found.")

    await db.delete(assignment)
    await db.flush()
