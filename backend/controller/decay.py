"""Decay scoring for the dashboard's Decay Tracker panel.

decision and failed_attempt never decay (see schema.PERMANENT_TYPES) and
are excluded here entirely. Everything else loses importance over time on
a per-type half-life, until a developer manually reinforces it back to 1.0.
"""
from __future__ import annotations

from datetime import datetime, timezone

from adapters.qdrant import QdrantAdapter
from schema import PERMANENT_TYPES, Memory, MemoryType

HALF_LIFE_DAYS: dict[MemoryType, float] = {
    "progress": 14.0,
    "test_result": 7.0,
    "bottleneck": 30.0,
    "current_state": 3.0,
    "next_step": 3.0,
}
DEFAULT_HALF_LIFE_DAYS = 14.0


def current_importance(memory: Memory, now: datetime | None = None) -> float:
    if memory.type in PERMANENT_TYPES:
        return 1.0
    now = now or datetime.now(timezone.utc)
    half_life = HALF_LIFE_DAYS.get(memory.type, DEFAULT_HALF_LIFE_DAYS)
    age_days = max(0.0, (now - memory.timestamp).total_seconds() / 86400)
    decayed = memory.importance * (0.5 ** (age_days / half_life))
    return max(0.0, min(1.0, decayed))


async def decay_ranked(
    project_id: str, adapter: QdrantAdapter, now: datetime | None = None
) -> list[dict]:
    """Non-permanent, active memories sorted by importance ascending."""
    memories = await adapter.list_all(project_id)
    ranked = [
        {"memory": m, "importance": current_importance(m, now)}
        for m in memories
        if m.type not in PERMANENT_TYPES and m.superseded_by is None
    ]
    ranked.sort(key=lambda r: r["importance"])
    return ranked


async def reinforce(memory_id: str, project_id: str, adapter: QdrantAdapter) -> Memory | None:
    memory = await adapter.get(project_id, memory_id)
    if memory is None:
        return None
    memory.importance = 1.0
    await adapter.store(memory)
    return memory
