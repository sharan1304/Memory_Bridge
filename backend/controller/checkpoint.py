"""checkpoint() MCP tool: cheap keyword gate, then async extraction."""
from __future__ import annotations

import asyncio
import logging

from groq import AsyncGroq

from adapters.sharedmenn import SharedMENNAdapter
from controller.extractor import extract_and_store
from schema import Agent

logger = logging.getLogger(__name__)

SIGNAL_KEYWORDS = [
    # failures
    "fail", "failed", "error", "broken", "issue", "bug",
    "crash", "exception", "wrong", "incorrect",
    # blockers
    "blocked", "stuck", "problem", "can't", "cannot",
    "unable", "missing", "not working",
    # decisions
    "decided", "chose", "chosen", "switched", "changed",
    "picked", "selected", "using", "adopted",
    # progress
    "completed", "finished", "done", "built", "implemented",
    "added", "created", "fixed", "resolved", "working",
    # tests
    "passed", "test", "verified", "confirmed",
    # forward looking
    "next", "todo", "need", "should", "will", "plan",
]


def has_signal(summary: str) -> bool:
    """Case-insensitive substring match, e.g. "failing" matches "fail"."""
    lowered = summary.lower()
    return any(keyword in lowered for keyword in SIGNAL_KEYWORDS)


async def checkpoint(
    project_id: str,
    session_id: str,
    agent: Agent,
    summary: str,
    status: str,
    files_changed: list[str],
    adapter: SharedMENNAdapter,
    groq_client: AsyncGroq | None = None,
) -> dict:
    """Returns immediately; storage runs in the background when signal is found."""
    if not has_signal(summary):
        return {"stored": False, "reason": "no signal keywords found"}

    asyncio.create_task(
        _extract_and_store_safely(project_id, session_id, agent, summary, adapter, groq_client)
    )
    return {"stored": True, "reason": "extraction scheduled"}


async def _extract_and_store_safely(
    project_id: str,
    session_id: str,
    agent: Agent,
    summary: str,
    adapter: SharedMENNAdapter,
    groq_client: AsyncGroq | None,
) -> None:
    # Runs detached from the MCP call, so nothing here may propagate - an
    # unreachable SharedMENN (surfaced as an ExceptionGroup) or a Groq failure
    # is logged and the checkpoint is dropped.
    try:
        await extract_and_store(project_id, session_id, agent, summary, adapter, client=groq_client)
    except Exception:
        logger.exception(
            "background memory extraction failed for project=%s (SharedMENN at %s)",
            project_id,
            adapter.base_url,
        )
