"""
engine/graph.py — Conflict graph construction.

The conflict graph is the "graph coloring" graph described in
system_architecture.md §4 and PROJECT_CONTEXT.md §23.

Graph structure:
  - One node per Session.
  - An undirected edge between sessions A and B means they CANNOT be
    placed in the same slot simultaneously.

Three edge types (from system_architecture.md §4, Step 3):
  1. Same faculty_id    -> edge  (faculty clash)
  2. Same section_id    -> edge  (section clash)
  3. Same ta_id         -> edge  (TA clash; only for non-None ta_ids)

Room conflicts are NOT pre-computed as graph edges.  Rooms are checked
dynamically during slot assignment in validator.py because room
availability changes as assignments are made.

Data structure:
  A dict mapping session.id -> set of conflicting session.ids.
  This is an adjacency list representation: O(1) neighbour lookup.

Usage in scheduler.py:
  - Degree ordering: sort by len(graph[session.id]) descending.
    Higher degree = more conflicted = schedule first.
  - Backtracking: when session S fails, look up graph[S.id] to find
    neighbours that were already assigned and are candidates for unassignment.

Entry point:
    graph = build_conflict_graph(sessions)
    neighbours = graph[session_id]  # set of session ids that conflict
"""

from __future__ import annotations

from app.engine.types import Session


def build_conflict_graph(sessions: list[Session]) -> dict[str, set[str]]:
    """
    Build an undirected conflict adjacency list for all sessions.

    Time complexity: O(N^2) where N = number of sessions.
    At single-department scale (N <= ~80) this is negligible.

    Args:
        sessions: All Session objects from the SchedulingContext.

    Returns:
        Adjacency list: session.id -> set of conflicting session.ids.
        Every session has an entry (possibly with an empty set).
    """
    graph: dict[str, set[str]] = {s.id: set() for s in sessions}

    n = len(sessions)
    for i in range(n):
        for j in range(i + 1, n):
            a = sessions[i]
            b = sessions[j]
            if _conflicts(a, b):
                graph[a.id].add(b.id)
                graph[b.id].add(a.id)

    return graph


def get_degree(graph: dict[str, set[str]], session_id: str) -> int:
    """
    Return the conflict degree of a session (number of conflicting neighbours).

    Used by scheduler.py for priority ordering: higher degree = schedule first.
    """
    return len(graph.get(session_id, set()))


# ── Internal helpers ──────────────────────────────────────────────────────────

def _conflicts(a: Session, b: Session) -> bool:
    """
    Return True if sessions A and B share at least one resource that would
    prevent them from being scheduled at the same time.

    Conflict conditions:
      - Same section: the student group cannot be in two places at once.
      - Same faculty: a faculty member cannot teach two sessions simultaneously.
      - Same TA: a TA cannot run two tutorials simultaneously.
        (Only applies when both sessions have a non-None ta_id that matches.)
    """
    # Same section (students can't be split across two simultaneous classes)
    if a.section_id == b.section_id:
        return True

    # Same faculty (professor can't teach two sessions at once)
    if a.faculty_id == b.faculty_id:
        return True

    # Same TA (only relevant if both sessions have a TA assigned)
    if (
        a.ta_id is not None
        and b.ta_id is not None
        and a.ta_id == b.ta_id
    ):
        return True

    return False
