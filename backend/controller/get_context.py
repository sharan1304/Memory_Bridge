"""Builds the handoff brief returned by the get_context() MCP tool."""
from __future__ import annotations

import logging

from adapters.sharedmenn import SharedMENNAdapter
from schema import Memory

logger = logging.getLogger(__name__)

# Permanent project facts: always fetched in full (type filter only, no
# semantic gate), up to these caps. A new agent must see every decision and
# every failed attempt regardless of what the current state happens to be
# about - gating these on similarity to current_state silently drops
# unrelated-but-important facts from the handoff brief.
ALWAYS_FETCH_LIMITS = {
    "decision": 10,
    "failed_attempt": 10,
    "bottleneck": 5,
}

# Contextual: only the ones relevant to the current state matter, so these
# stay semantic-search-gated, each independently capped at its own top_k
# (adapter.semantic_search's top_k is a combined cap across all requested
# types, so test_result and progress each need their own call to get 3 of
# each rather than 3 split between them).
SEMANTIC_TOP_K = {
    "test_result": 3,
    "progress": 3,
}

SECTION_TITLES = {
    "decision": "DECISIONS MADE",
    "failed_attempt": "WHAT WAS TRIED AND FAILED",
    "bottleneck": "ACTIVE BOTTLENECKS",
    "test_result": "RECENT TEST RESULTS",
    "progress": "RECENT PROGRESS",
}

# CURRENT STATE and NEXT STEP are handled separately (always pinned, always
# first); this is the order for everything else in the brief.
SECTION_ORDER = ("decision", "failed_attempt", "bottleneck", "test_result", "progress")

FALLBACK_QUERY = "project context and recent progress"

UNAVAILABLE_BRIEF = (
    "CURRENT STATE: SharedMENN is unavailable - no stored project memory could be retrieved.\n"
    "\n"
    "NEXT STEP:\n"
    "• Proceed from the repository itself; prior decisions and failed attempts are not loaded.\n"
)


def _format_brief(
    current_state: Memory | None,
    next_step: Memory | None,
    by_type: dict[str, list[Memory]],
) -> str:
    lines: list[str] = []

    lines.append(
        f"CURRENT STATE: {current_state.content if current_state else 'No current state recorded yet.'}"
    )
    lines.append("")

    lines.append("NEXT STEP:")
    lines.append(f"• {next_step.content if next_step else 'Not yet determined.'}")
    lines.append("")

    for type_ in SECTION_ORDER:
        memories = by_type.get(type_, [])
        if not memories:
            continue
        lines.append(f"{SECTION_TITLES[type_]}:")
        for m in memories:
            lines.append(f"• {m.content}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


async def get_context(project_id: str, adapter: SharedMENNAdapter) -> tuple[str, list[str]]:
    """Returns (handoff_brief, memory_ids_retrieved).

    Never raises on SharedMENN failures: an unreachable SharedMENN (network,
    TLS, auth - the MCP client surfaces these as an ExceptionGroup from its
    TaskGroup) yields a minimal brief saying so, rather than a tool error.
    """
    try:
        return await _build_context(project_id, adapter)
    except Exception:
        logger.exception(
            "SharedMENN unavailable at %s; returning fallback brief for project=%s",
            adapter.base_url,
            project_id,
        )
        return UNAVAILABLE_BRIEF, []


async def _build_context(project_id: str, adapter: SharedMENNAdapter) -> tuple[str, list[str]]:
    current_state_list = await adapter.fetch_by_type(project_id, "current_state", limit=1)
    next_step_list = await adapter.fetch_by_type(project_id, "next_step", limit=1)

    current_state = current_state_list[0] if current_state_list else None
    next_step = next_step_list[0] if next_step_list else None

    by_type: dict[str, list[Memory]] = {}

    for type_, limit in ALWAYS_FETCH_LIMITS.items():
        results = await adapter.fetch_by_type(project_id, type_, limit=limit)
        if results:
            by_type[type_] = results

    query = current_state.content if current_state else FALLBACK_QUERY
    for type_, top_k in SEMANTIC_TOP_K.items():
        # Relevance-ordered by semantic_search itself - not re-sorted by
        # timestamp, since "most relevant to current state" is the point.
        results = await adapter.semantic_search(project_id, query=query, types=[type_], top_k=top_k)
        if results:
            by_type[type_] = results

    brief = _format_brief(current_state, next_step, by_type)

    memory_ids = [m.id for m in ([current_state] if current_state else [])]
    memory_ids += [m.id for m in ([next_step] if next_step else [])]
    for type_ in SECTION_ORDER:
        memory_ids += [m.id for m in by_type.get(type_, [])]

    return brief, memory_ids
