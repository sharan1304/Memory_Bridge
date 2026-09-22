"""Heuristic conflict detection for the dashboard's Conflict Monitor panel.

Flags pairs of active, same-type memories whose content is similar enough
to be about the same subject but not identical - a proxy for "these two
facts might disagree." It's intentionally simple (text similarity plus a
keyword check), not an LLM judgment call; resolving a flagged pair (keep
one / merge / discard both) is a developer action taken through the
existing memory CRUD endpoints.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from itertools import combinations

from adapters.sharedmenn import SharedMENNAdapter
from schema import Memory

CONFLICT_TYPES = ("decision", "current_state", "next_step", "bottleneck")
SIMILARITY_THRESHOLD = 0.75
CONTRADICTION_MARKERS = (
    "instead", "reverted", "switched", "no longer", "abandoned",
    "changed from", "rather than", "not ",
)


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _looks_contradictory(a: str, b: str) -> bool:
    lowered = f"{a} {b}".lower()
    return any(marker in lowered for marker in CONTRADICTION_MARKERS)


async def find_conflicts(project_id: str, adapter: SharedMENNAdapter) -> list[dict]:
    memories = await adapter.list_all(project_id)
    active = [m for m in memories if m.superseded_by is None and m.type in CONFLICT_TYPES]

    conflicts: list[dict] = []
    for a, b in combinations(active, 2):
        if a.type != b.type:
            continue
        if a.content.strip().lower() == b.content.strip().lower():
            continue
        similarity = _similarity(a.content, b.content)
        if similarity < SIMILARITY_THRESHOLD:
            continue
        conflicts.append(
            {
                "memory_a": a,
                "memory_b": b,
                "similarity": round(similarity, 2),
                "likely_contradiction": _looks_contradictory(a.content, b.content),
            }
        )
    conflicts.sort(key=lambda c: c["similarity"], reverse=True)
    return conflicts
