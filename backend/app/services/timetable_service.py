"""
services/timetable_service.py — Timetable orchestration and management.

Responsibilities:
  - generate_timetable: Load context → run engine (in thread pool) →
    rotate snapshots → bulk-insert entries → save conflict report.
  - get_active_timetable: Fetch the ACTIVE timetable for a semester.
  - get_timetable_by_id: Fetch any timetable by UUID.
  - get_timetable_entries: Filtered + paginated entry query.
  - get_conflict_report: Read and parse the JSONB conflict report.
  - delete_timetable: Hard-delete (CASCADE removes entries + report).
  - export_timetable_csv: Build and return a CSV string from entries.

Design principles:
  - NO HTTP knowledge. Business-rule violations raise plain ValueError.
    The route layer converts these to HTTP responses.
  - The scheduler engine is called via asyncio.run_in_executor (thread pool)
    so it does not block the FastAPI event loop. The engine is CPU-bound
    Python (graph traversal, backtracking) — it must run in a thread.
  - All DB writes for a single generation run in ONE transaction.
    The route layer commits. If any step fails, the full rollback is clean.
  - Snapshot rotation happens INSIDE the generate transaction:
    old ACTIVE → SNAPSHOT, old SNAPSHOT deleted, new ACTIVE inserted.

Scheduler Engine Interface (STUB):
  The engine directory (app/engine/) currently contains only __init__.py.
  This service imports from app.engine via a well-defined interface so the
  engine modules can be implemented independently without changing this file.

  Expected interface (to be implemented in app/engine/):
    from app.engine import run_scheduler
    result = run_scheduler(context: SchedulingContext) -> SchedulingResult

  Where:
    SchedulingContext — dataclass built from DB data
    SchedulingResult  — dataclass with:
        assignments:   list[SessionAssignment]  (scheduled sessions)
        unscheduled:   list[UnscheduledSession] (sessions that failed)
        warnings:      list[str]                (pre-generation warnings)

  Until the engine is implemented, generate_timetable uses _STUB_ENGINE
  which returns an empty result (0 sessions scheduled, 0 conflicts).
  This lets the full API surface work end-to-end immediately.

  To activate the real engine: replace _run_engine_stub with:
    from app.engine import run_scheduler
    result = await asyncio.get_event_loop().run_in_executor(
        None, run_scheduler, context
    )

Snapshot strategy (per system_architecture.md §5 Snapshot Strategy):
  1. Load current ACTIVE timetable (if any).
  2. Load current SNAPSHOT (if any) — delete it.
  3. Demote current ACTIVE → SNAPSHOT.
  4. Insert new Timetable with status=ACTIVE.
  This guarantees: at most 2 timetables per semester at any time.

CSV export format (per system_architecture.md §9 Export Flow):
  Rows = time slots (8–18), Columns = days (Mon–Fri).
  Each cell: "COURSE_CODE / SESSION_TYPE / ROOM_NAME" or empty.
  Header row: "Slot,MON,TUE,WED,THU,FRI"

Error contract:
  generate_timetable   → ValueError("Semester not found.")
                       → ValueError("Semester is not active. ...")
                       → ValueError("No course assignments found. ...")
  get_active_timetable → returns None if no ACTIVE timetable
  get_conflict_report  → ValueError("Timetable not found.")
  delete_timetable     → ValueError("Timetable not found.")
  export_timetable_csv → ValueError("Timetable not found.")
"""

import asyncio
import csv
import io
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course_assignment import CourseAssignment
from app.models.enums import TimetableStatus, SessionType, DayOfWeek
from app.models.semester import Semester
from app.models.timetable import ConflictReport, Timetable, TimetableEntry
from app.schemas.timetable import ConflictItemRead


# ══════════════════════════════════════════════════════════════════════════════
# Scheduler Engine
# ══════════════════════════════════════════════════════════════════════════════
# The real engine is now implemented in app/engine/.
# build_context loads DB data into pure-Python dataclasses.
# run_scheduler executes the graph-coloring + greedy + backtracking algorithm
# synchronously, so it is offloaded to a thread pool via run_in_executor.
# ══════════════════════════════════════════════════════════════════════════════

from app.engine import run_scheduler
from app.engine.context import build_context
from app.engine.types import SchedulingResult


async def _run_engine(
    db: AsyncSession,
    semester_id: uuid.UUID,
) -> SchedulingResult:
    """
    Build the scheduling context from the DB and run the scheduler engine
    in a thread pool executor (non-blocking for the FastAPI event loop).

    Args:
        db:          Active async SQLAlchemy session.
        semester_id: Semester to schedule.

    Returns:
        SchedulingResult with .assignments, .unscheduled, .warnings
    """
    # Build context (async DB reads)
    context = await build_context(db, semester_id)

    # Run the CPU-bound scheduler in a thread pool so it doesn't
    # block the async event loop.
    loop = asyncio.get_event_loop()
    result: SchedulingResult = await loop.run_in_executor(
        None, run_scheduler, context
    )
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Core Service Functions
# ══════════════════════════════════════════════════════════════════════════════

async def get_active_timetable(
    db: AsyncSession,
    semester_id: uuid.UUID,
) -> Timetable | None:
    """
    Return the ACTIVE timetable for a semester, or None if none exists.

    Uses idx_timetables_semester_status (composite index) for O(log n) lookup.
    """
    result = await db.execute(
        select(Timetable).where(
            Timetable.semester_id == semester_id,
            Timetable.status == TimetableStatus.ACTIVE,
        )
    )
    return result.scalars().first()


async def get_timetable_by_id(
    db: AsyncSession,
    timetable_id: uuid.UUID,
) -> Timetable | None:
    """Return a Timetable by UUID, or None if not found."""
    return await db.get(Timetable, timetable_id)


async def generate_timetable(
    db: AsyncSession,
    semester_id: uuid.UUID,
    admin_id: uuid.UUID,
) -> dict:
    """
    Generate a new timetable for the given semester.

    Steps:
      1. Validate semester exists and is_active=True.
      2. Validate that course assignments exist (otherwise generation is pointless).
      3. Run the scheduler engine (stub or real) in a thread pool.
      4. Snapshot rotation:
         a. Find current SNAPSHOT (if any) → delete it.
         b. Demote current ACTIVE (if any) → SNAPSHOT.
      5. Insert new Timetable with status=ACTIVE.
      6. Bulk-insert TimetableEntry rows from engine result.
      7. Insert ConflictReport with the JSONB conflict list.
      8. flush() — route commits.

    Returns:
      dict with keys: timetable_id, warnings, conflict_count, snapshot_id

    Raises:
      ValueError("Semester not found.")
      ValueError("Semester is not active. ...")
      ValueError("No course assignments found. ...")
    """
    # ── Step 1: validate semester ──────────────────────────────────────
    semester = await db.get(Semester, semester_id)
    if semester is None:
        raise ValueError(f"Semester {semester_id} not found.")
    if not semester.is_active:
        raise ValueError(
            f"Semester '{semester.name}' is not the active semester. "
            "Set it as active before generating a timetable."
        )

    # ── Step 2: validate assignments exist ────────────────────────────
    count_result = await db.execute(
        select(func.count())
        .select_from(CourseAssignment)
        .join(CourseAssignment.course)
        .where(CourseAssignment.course.has(semester_id=semester_id))
    )
    assignment_count: int = count_result.scalar_one()
    if assignment_count == 0:
        raise ValueError(
            "No course assignments found for this semester. "
            "Add course assignments before generating a timetable."
        )

    # ── Step 3: run the real scheduler engine ────────────────────────
    engine_result = await _run_engine(db=db, semester_id=semester_id)

    # ── Step 4: snapshot rotation ─────────────────────────────────────
    snapshot_id: uuid.UUID | None = None

    # 4a: find and delete old SNAPSHOT
    old_snapshot_result = await db.execute(
        select(Timetable).where(
            Timetable.semester_id == semester_id,
            Timetable.status == TimetableStatus.SNAPSHOT,
        )
    )
    old_snapshot = old_snapshot_result.scalars().first()
    if old_snapshot is not None:
        await db.delete(old_snapshot)
        await db.flush()  # ensure delete completes before demote

    # 4b: demote current ACTIVE → SNAPSHOT
    current_active = await get_active_timetable(db=db, semester_id=semester_id)
    if current_active is not None:
        snapshot_id = current_active.id
        current_active.status = TimetableStatus.SNAPSHOT
        await db.flush()

    # ── Step 5: insert new ACTIVE timetable ───────────────────────────
    new_timetable = Timetable(
        semester_id=semester_id,
        status=TimetableStatus.ACTIVE,
        generated_at=datetime.now(timezone.utc),
        generated_by=admin_id,
    )
    db.add(new_timetable)
    await db.flush()  # populate new_timetable.id

    # ── Step 6: bulk-insert TimetableEntry rows ───────────────────────
    entries: list[TimetableEntry] = []
    for a in engine_result.assignments:
        entry = TimetableEntry(
            timetable_id=new_timetable.id,
            assignment_id=a.assignment_id,
            session_type=SessionType[a.session_type],
            day=DayOfWeek[a.day],
            start_slot=a.start_slot,
            end_slot=a.end_slot,
            room_id=a.room_id,
            section_id=a.section_id,
            faculty_id=a.faculty_id,
            ta_id=a.ta_id,
        )
        entries.append(entry)

    if entries:
        db.add_all(entries)
        await db.flush()

    # ── Step 7: insert ConflictReport ─────────────────────────────────
    # Build JSONB list from unscheduled sessions
    conflict_items: list[dict] = []
    for u in engine_result.unscheduled:
        if isinstance(u, dict):
            conflict_items.append(u)
        elif hasattr(u, "to_dict"):
            conflict_items.append(u.to_dict())
        else:
            conflict_items.append({"reason_detail": str(u)})

    conflict_report = ConflictReport(
        timetable_id=new_timetable.id,
        report=conflict_items,
    )
    db.add(conflict_report)
    await db.flush()

    return {
        "timetable_id": new_timetable.id,
        "warnings": engine_result.warnings,
        "conflict_count": len(conflict_items),
        "snapshot_id": snapshot_id,
    }


async def get_timetable_entries(
    db: AsyncSession,
    timetable_id: uuid.UUID,
    section_id: uuid.UUID | None = None,
    faculty_id: uuid.UUID | None = None,
    room_id: uuid.UUID | None = None,
    day: str | None = None,
    skip: int = 0,
    limit: int = 200,
) -> tuple[int, list[TimetableEntry]]:
    """
    Return a (total_count, page) tuple of TimetableEntry rows.

    Filters are AND-ed together.  Ordered: day ASC, start_slot ASC.
    Uses the appropriate composite index for the active filter:
      idx_te_section_day, idx_te_faculty_day, idx_te_room_day.

    Args:
      timetable_id: Required — always scoped to one timetable.
      section_id:   Optional filter by section.
      faculty_id:   Optional filter by faculty member.
      room_id:      Optional filter by room.
      day:          Optional filter by day (e.g. "MON").
      skip, limit:  Pagination.
    """
    filters = [TimetableEntry.timetable_id == timetable_id]
    if section_id is not None:
        filters.append(TimetableEntry.section_id == section_id)
    if faculty_id is not None:
        filters.append(TimetableEntry.faculty_id == faculty_id)
    if room_id is not None:
        filters.append(TimetableEntry.room_id == room_id)
    if day is not None:
        filters.append(TimetableEntry.day == day)

    count_result = await db.execute(
        select(func.count()).select_from(TimetableEntry).where(*filters)
    )
    total: int = count_result.scalar_one()

    data_result = await db.execute(
        select(TimetableEntry)
        .where(*filters)
        .order_by(TimetableEntry.day.asc(), TimetableEntry.start_slot.asc())
        .offset(skip)
        .limit(limit)
    )
    entries = list(data_result.scalars().all())

    return total, entries


async def get_conflict_report(
    db: AsyncSession,
    timetable_id: uuid.UUID,
) -> dict:
    """
    Return the conflict report for a timetable.

    Returns:
      dict with keys: timetable_id, total, conflicts (list of ConflictItemRead)

    Raises:
      ValueError("Timetable not found.") — if timetable_id doesn't exist.
    """
    timetable = await get_timetable_by_id(db=db, timetable_id=timetable_id)
    if timetable is None:
        raise ValueError(f"Timetable {timetable_id} not found.")

    # conflict_report is loaded via lazy="selectin" on the Timetable relationship
    report_obj = timetable.conflict_report
    raw_items: list[dict] = report_obj.report if report_obj is not None else []

    # Parse JSONB items into ConflictItemRead for type safety
    parsed_items = [ConflictItemRead(**item) for item in raw_items]

    return {
        "timetable_id": timetable_id,
        "total": len(parsed_items),
        "conflicts": parsed_items,
    }


async def delete_timetable(
    db: AsyncSession,
    timetable_id: uuid.UUID,
) -> None:
    """
    Hard-delete a timetable.

    Cascade (confirmed in migration):
      timetable_entries.timetable_id → ON DELETE CASCADE
      conflict_reports.timetable_id  → ON DELETE CASCADE

    All entries and the conflict report are deleted automatically.

    Raises:
      ValueError("Timetable not found.") — if timetable_id doesn't exist.
    """
    timetable = await get_timetable_by_id(db=db, timetable_id=timetable_id)
    if timetable is None:
        raise ValueError(f"Timetable {timetable_id} not found.")

    await db.delete(timetable)
    await db.flush()


async def export_timetable_csv(
    db: AsyncSession,
    timetable_id: uuid.UUID,
    export_type: str,
    filter_id: uuid.UUID | None = None,
) -> tuple[str, str]:
    """
    Build and return a CSV string for the timetable.

    The CSV represents a weekly schedule grid:
      Rows:    time slots (8 to 17, inclusive)
      Columns: days (MON, TUE, WED, THU, FRI)
      Cells:   "COURSE_CODE / SESSION_TYPE / ROOM" or empty string

    Args:
      db:           Async DB session.
      timetable_id: The timetable to export.
      export_type:  "SECTION" | "FACULTY" | "ROOM" | "FULL"
      filter_id:    UUID of the section/faculty/room (required for non-FULL exports).

    Returns:
      (csv_string, suggested_filename) — the CSV content and a filename.

    Raises:
      ValueError("Timetable not found.") — if timetable_id doesn't exist.
      ValueError("filter_id required for ...") — if filter_id is missing for non-FULL.
    """
    timetable = await get_timetable_by_id(db=db, timetable_id=timetable_id)
    if timetable is None:
        raise ValueError(f"Timetable {timetable_id} not found.")

    export_type_upper = export_type.upper()

    # Validate filter_id for non-FULL exports
    if export_type_upper != "FULL" and filter_id is None:
        raise ValueError(
            f"filter_id is required for export_type={export_type_upper}."
        )

    # Build query filters
    filters = [TimetableEntry.timetable_id == timetable_id]
    if export_type_upper == "SECTION" and filter_id is not None:
        filters.append(TimetableEntry.section_id == filter_id)
    elif export_type_upper == "FACULTY" and filter_id is not None:
        filters.append(TimetableEntry.faculty_id == filter_id)
    elif export_type_upper == "ROOM" and filter_id is not None:
        filters.append(TimetableEntry.room_id == filter_id)

    # Fetch matching entries
    result = await db.execute(
        select(TimetableEntry).where(*filters)
    )
    entries: list[TimetableEntry] = list(result.scalars().all())

    # Build a lookup: (day, start_slot) → list of cell strings
    # Using list because labs span multiple slots
    _DAYS = ["MON", "TUE", "WED", "THU", "FRI"]
    _SLOTS = list(range(8, 18))  # 8 to 17 inclusive

    # Grid: day → slot → list of cell label strings
    grid: dict[str, dict[int, list[str]]] = {
        day: {slot: [] for slot in _SLOTS}
        for day in _DAYS
    }

    # Fetch room names for display
    # We need room names in the cell — load them via a simple select
    room_ids = {e.room_id for e in entries}
    room_name_map: dict[uuid.UUID, str] = {}
    if room_ids:
        from app.models.room import Room
        rooms_result = await db.execute(
            select(Room.id, Room.name).where(Room.id.in_(room_ids))
        )
        for row in rooms_result:
            room_name_map[row[0]] = row[1]

    # Fetch section names
    section_ids = {e.section_id for e in entries}
    section_name_map: dict[uuid.UUID, str] = {}
    if section_ids:
        from app.models.section import Section
        sections_result = await db.execute(
            select(Section.id, Section.name).where(Section.id.in_(section_ids))
        )
        for row in sections_result:
            section_name_map[row[0]] = row[1]

    # Fetch user full names (for faculty and TA)
    user_ids = {e.faculty_id for e in entries}.union({e.ta_id for e in entries if e.ta_id})
    user_name_map: dict[uuid.UUID, str] = {}
    if user_ids:
        from app.models.user import User
        users_result = await db.execute(
            select(User.id, User.full_name).where(User.id.in_(user_ids))
        )
        for row in users_result:
            user_name_map[row[0]] = row[1]

    # Fetch course codes for display
    assignment_ids = {e.assignment_id for e in entries}
    course_code_map: dict[uuid.UUID, str] = {}
    if assignment_ids:
        from app.models.course import Course
        code_result = await db.execute(
            select(CourseAssignment.id, Course.code)
            .join(Course, CourseAssignment.course_id == Course.id)
            .where(CourseAssignment.id.in_(assignment_ids))
        )
        for row in code_result:
            course_code_map[row[0]] = row[1]

    # Populate grid
    for entry in entries:
        day_str = entry.day.value if hasattr(entry.day, "value") else str(entry.day)
        if day_str not in grid:
            continue
        course_code = course_code_map.get(entry.assignment_id, "?")
        session_type = (
            entry.session_type.value
            if hasattr(entry.session_type, "value")
            else str(entry.session_type)
        )
        session_display = session_type.capitalize()
        room_name = room_name_map.get(entry.room_id, "?")
        section_name = section_name_map.get(entry.section_id, "?")
        faculty_name = user_name_map.get(entry.faculty_id, "?")
        
        lines = [
            section_name,
            f"{course_code} ({session_display})"
        ]
        
        if session_type != "TUTORIAL":
            lines.append(f"Faculty: {faculty_name}")
            
        if entry.ta_id and session_type in ("TUTORIAL", "LAB"):
            ta_name = user_name_map.get(entry.ta_id, "?")
            lines.append(f"TA: {ta_name}")
            
        lines.append(room_name)
        
        cell_label = "\n".join(lines)

        # Fill all slots this session occupies (start_slot to end_slot - 1)
        for slot in range(entry.start_slot, entry.end_slot):
            if slot in grid[day_str]:
                grid[day_str][slot].append(cell_label)

    # Serialize to CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow(["Slot", "MON", "TUE", "WED", "THU", "FRI"])

    for slot in _SLOTS:
        row = [f"{slot}:00–{slot+1}:00"]
        for day in _DAYS:
            cell_entries = grid[day][slot]
            row.append("\n\n--------------------\n\n".join(cell_entries) if cell_entries else "")
        writer.writerow(row)

    csv_string = output.getvalue()

    # Build filename
    if export_type_upper == "FULL":
        filename = f"timetable_{timetable_id}_full.csv"
    else:
        filter_label = str(filter_id)[:8] if filter_id else "all"
        filename = f"timetable_{timetable_id}_{export_type_upper.lower()}_{filter_label}.csv"

    return csv_string, filename
