"""
engine/scheduler.py — Main scheduling pipeline.

This is the core of the engine.  It runs entirely in memory on the
SchedulingContext built by context.py, and returns a SchedulingResult.

Algorithm (matches system_architecture.md §4 Steps 4-5):

  Step 1: Build conflict graph (graph.py)
  Step 2: Sort sessions by priority (deterministic ordering)
  Step 3: For each session in priority order:
            For each candidate day:
              For each candidate slot in [SLOT_START, SLOT_END]:
                For each candidate room (best-fit order):
                  If check_all_constraints passes:
                    Assign -> record in state -> break
          If no slot found -> backtrack -> retry -> mark UNSCHEDULED

Priority ordering (deterministic, per system_architecture.md §4 Step 4):
  1. Tier (TIER_1=highest priority, TIER_4=lowest)
     - Ensures 4-credit courses get the best slots first
  2. Conflict graph degree descending
     - Most constrained session gets scheduled first (graph coloring heuristic)
  3. Tie-break: course_name A-Z, then section_name A-Z
     - Guarantees identical inputs always produce identical outputs

Backtracking strategy (bounded, per system_architecture.md §4 Step 5):
  When a session cannot be placed:
    1. Find its graph-neighbours that have already been assigned
    2. Sort by "most recently assigned" (so we undo the latest decision first)
    3. Unassign up to MAX_BT_DEPTH neighbours, one at a time
    4. Re-attempt slot search after each unassignment
    5. If still failing after MAX_BT_DEPTH attempts: mark UNSCHEDULED

  The unassigned neighbours are placed back in the to-schedule queue at
  the front (they retry immediately after the blocking session is placed).

  This bounded backtracking prevents exponential blowup while still
  recovering from many common conflict situations.

Room selection (best-fit):
  Rooms of the correct type are sorted by capacity ASC.
  We pick the smallest room whose capacity >= section.strength.
  This minimises wasted room capacity (best-fit bin packing).

Entry point:
    result = run_scheduler(ctx)

This function is synchronous and CPU-bound.  timetable_service.py calls it
via asyncio.run_in_executor to avoid blocking the FastAPI event loop.
"""

from __future__ import annotations

import uuid
from collections import defaultdict, deque
from typing import Optional

from app.engine.conflict import build_conflict_report
from app.engine.graph import build_conflict_graph, get_degree
from app.engine.pre_validator import run_pre_validation
from app.engine.types import (
    DAYS,
    MAX_BT_DEPTH,
    SESSION_ROOM_TYPE,
    SLOT_END,
    SLOT_START,
    RoomInfo,
    SchedulingContext,
    SchedulingResult,
    Session,
    SlotAssignment,
    UnscheduledSession,
    ReasonCode,
)
from app.engine.validator import (
    StateIndex,
    check_all_constraints,
    make_state_index,
    record_assignment,
    remove_assignment,
)


# ── Tier priority mapping (lower number = higher priority) ────────────────────
_TIER_PRIORITY: dict[str, int] = {
    "TIER_1": 1,
    "TIER_2": 2,
    "TIER_3": 3,
    "TIER_4": 4,
}


def run_scheduler(ctx: SchedulingContext) -> SchedulingResult:
    """
    Run the full scheduling pipeline and return a SchedulingResult.

    This function is the public entry point of the engine.
    It is synchronous and intended to run in a thread pool executor.

    Args:
        ctx: A fully populated SchedulingContext from context.py.

    Returns:
        A SchedulingResult with:
          - assignments:  all successfully placed sessions
          - unscheduled:  all sessions that could not be placed
          - warnings:     pre-generation feasibility warnings
    """
    # ── Pre-validation ────────────────────────────────────────────────────────
    warnings = run_pre_validation(ctx)

    if not ctx.sessions:
        return SchedulingResult(warnings=warnings)

    # ── Build conflict graph ──────────────────────────────────────────────────
    graph = build_conflict_graph(ctx.sessions)

    # ── Priority ordering ─────────────────────────────────────────────────────
    ordered = _priority_sort(ctx.sessions, graph)

    # ── Rooms grouped by type for fast lookup ─────────────────────────────────
    rooms_by_type: dict[str, list[RoomInfo]] = defaultdict(list)
    for room in ctx.rooms:
        rooms_by_type[room.room_type].append(room)
    # Each group is already sorted capacity ASC (rooms loaded in that order by context.py)

    # ── Initialize state index ────────────────────────────────────────────────
    state = make_state_index()

    # ── Session ID -> Session object lookup ───────────────────────────────────
    session_lookup: dict[str, Session] = {s.id: s for s in ctx.sessions}

    # ── Scheduling queue as a deque (allows prepend for backtracked sessions) ──
    queue: deque[Session] = deque(ordered)

    # Track which sessions are successfully assigned
    assigned_ids: set[str] = set()

    # Track sessions that ultimately failed after all backtracking attempts
    failed_sessions: list[Session] = []

    # Conflict detail tracking: session_id -> list of violated constraint codes
    conflict_details: dict[str, list[str]] = defaultdict(list)

    # ── Main scheduling loop ──────────────────────────────────────────────────
    while queue:
        session = queue.popleft()

        if session.id in assigned_ids:
            # Already placed (can happen when popped from backtrack re-queue)
            continue

        assignment, all_violations = _try_assign(
            session, rooms_by_type, state, ctx
        )

        if assignment is not None:
            # Success
            record_assignment(state, session, assignment)
            assigned_ids.add(session.id)
        else:
            # Failed — attempt bounded backtracking
            conflict_details[session.id].extend(all_violations)

            placed = _backtrack_and_retry(
                session=session,
                graph=graph,
                state=state,
                ctx=ctx,
                rooms_by_type=rooms_by_type,
                assigned_ids=assigned_ids,
                session_lookup=session_lookup,
                queue=queue,
                conflict_details=conflict_details,
            )

            if placed:
                assigned_ids.add(session.id)
            else:
                # Mark as unscheduled and continue with the rest
                if ReasonCode.BACKTRACK_EXHAUSTED not in conflict_details[session.id]:
                    conflict_details[session.id].append(ReasonCode.BACKTRACK_EXHAUSTED)
                failed_sessions.append(session)

    # ── Build unscheduled session objects ─────────────────────────────────────
    unscheduled = build_conflict_report(failed_sessions, conflict_details)

    return SchedulingResult(
        assignments=state.assignments,
        unscheduled=unscheduled,
        warnings=warnings,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Priority ordering
# ═════════════════════════════════════════════════════════════════════════════

def _priority_sort(
    sessions: list[Session],
    graph: dict[str, set[str]],
) -> list[Session]:
    """
    Sort sessions by scheduling priority (deterministic).

    Key (ascending):
      1. Tier priority (TIER_1=1 ... TIER_4=4)  — lower is better
      2. Conflict degree descending               — more edges = schedule first
      3. course_name ascending                   — stable tie-break
      4. section_name ascending                  — stable tie-break
    """
    return sorted(
        sessions,
        key=lambda s: (
            _TIER_PRIORITY.get(s.tier, 99),     # tier priority ASC
            -get_degree(graph, s.id),           # degree DESC
            s.course_name,                      # name ASC
            s.section_name,                     # section ASC
        )
    )


# ═════════════════════════════════════════════════════════════════════════════
# Assignment attempt
# ═════════════════════════════════════════════════════════════════════════════

def _try_assign(
    session: Session,
    rooms_by_type: dict[str, list[RoomInfo]],
    state: StateIndex,
    ctx: SchedulingContext,
) -> tuple[Optional[SlotAssignment], list[str]]:
    """
    Try every (day, slot, room) candidate for this session.

    Returns:
        (SlotAssignment, []) on success
        (None, all_violation_codes) on failure
    """
    required_room_type = SESSION_ROOM_TYPE.get(session.session_type, "LECTURE_HALL")
    candidate_rooms = rooms_by_type.get(required_room_type, [])

    # Filter to rooms that can hold this section (best-fit: sorted ASC, pick first)
    eligible_rooms = [r for r in candidate_rooms if r.capacity >= session.section_strength]

    if not eligible_rooms:
        return None, [ReasonCode.NO_VALID_ROOM]

    all_violations: list[str] = []

    for day in DAYS:
        for start_slot in _candidate_slots(session, day):
            for room in eligible_rooms:
                passed, violations = check_all_constraints(
                    session=session,
                    day=day,
                    start_slot=start_slot,
                    room=room,
                    state=state,
                    ctx=ctx,
                )
                if passed:
                    end_slot = start_slot + session.duration
                    return SlotAssignment(
                        assignment_id=session.assignment_id,
                        session_type=session.session_type,
                        day=day,
                        start_slot=start_slot,
                        end_slot=end_slot,
                        room_id=room.id,
                        section_id=session.section_id,
                        faculty_id=session.faculty_id,
                        ta_id=session.ta_id,
                    ), []
                else:
                    # Accumulate violations (unique)
                    for v in violations:
                        if v not in all_violations:
                            all_violations.append(v)

    return None, all_violations


def _candidate_slots(session: Session, day: str) -> list[int]:
    """
    Return valid start_slot values for a session on a given day.

    For 1-slot sessions: all slots from SLOT_START to SLOT_END.
    For multi-slot sessions: slots where [start, start+duration) fits
    within [SLOT_START, SLOT_END+1].
    
    Hard blocks slot 12 (12:00 - 13:00) globally.
    """
    max_start = SLOT_END - session.duration + 1
    slots = []
    for s in range(SLOT_START, max_start + 1):
        if 12 not in range(s, s + session.duration):
            slots.append(s)
    return slots


# ═════════════════════════════════════════════════════════════════════════════
# Bounded backtracking
# ═════════════════════════════════════════════════════════════════════════════

def _backtrack_and_retry(
    session: Session,
    graph: dict[str, set[str]],
    state: StateIndex,
    ctx: SchedulingContext,
    rooms_by_type: dict[str, list[RoomInfo]],
    assigned_ids: set[str],
    session_lookup: dict[str, Session],
    queue: deque[Session],
    conflict_details: dict[str, list[str]],
) -> bool:
    """
    Attempt to place a failed session by unassigning conflicting neighbours.

    Strategy:
      1. Find all graph-neighbours of this session that are currently assigned.
      2. Sort by reverse assignment order (most recently assigned first).
      3. Unassign one neighbour at a time, retry the session, up to MAX_BT_DEPTH.
      4. If retry succeeds: re-queue the unassigned neighbour at the front.
      5. If all attempts fail: return False (caller marks session UNSCHEDULED).

    Returns:
        True  — session was successfully placed after backtracking.
        False — all backtracking attempts failed.
    """
    neighbours = graph.get(session.id, set())

    # Find assigned neighbours sorted most-recent first
    # We approximate "most recent" by reverse order in state.assignments
    assigned_neighbours: list[tuple[int, SlotAssignment, Session]] = []

    for a in reversed(state.assignments):
        # Determine which session produced this assignment
        # We need to find the session_id whose assignment_id and session_type match
        # Search through all sessions matching this assignment
        neighbour_session_id = _find_session_id_for_assignment(
            a, session_lookup, neighbours
        )
        if neighbour_session_id is None:
            continue
        assigned_neighbours.append((len(assigned_neighbours), a, session_lookup[neighbour_session_id]))
        if len(assigned_neighbours) >= MAX_BT_DEPTH:
            break

    # Try unassigning each neighbour in turn
    for _, neighbour_assignment, neighbour_session in assigned_neighbours:
        # Unassign the neighbour
        remove_assignment(state, neighbour_session, neighbour_assignment)
        assigned_ids.discard(neighbour_session.id)

        # Retry assigning the failing session
        assignment, violations = _try_assign(session, rooms_by_type, state, ctx)

        if assignment is not None:
            # Success: record this session, re-queue the displaced neighbour
            record_assignment(state, session, assignment)
            # Re-add displaced neighbour to the front of the queue for retry
            queue.appendleft(neighbour_session)
            return True
        else:
            # Still failing: undo the unassignment, try the next neighbour
            record_assignment(state, neighbour_session, neighbour_assignment)
            assigned_ids.add(neighbour_session.id)
            for v in violations:
                if v not in conflict_details[session.id]:
                    conflict_details[session.id].append(v)

    return False


def _find_session_id_for_assignment(
    assignment: SlotAssignment,
    session_lookup: dict[str, Session],
    candidate_ids: set[str],
) -> Optional[str]:
    """
    Given a SlotAssignment, find the session_id in candidate_ids that
    produced it (matching assignment_id and session_type).

    Returns the session_id or None if not found in candidates.
    """
    for sid in candidate_ids:
        session = session_lookup.get(sid)
        if session is None:
            continue
        if (session.assignment_id == assignment.assignment_id
                and session.session_type == assignment.session_type
                and assignment.day is not None):
            return sid
    return None
