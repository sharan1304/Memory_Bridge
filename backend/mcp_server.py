"""Registers get_context and checkpoint as MCP tools for Claude Code and Codex.

Also exposes the same underlying data as MCP resources (mennbridge://context,
mennbridge://memories, mennbridge://status), for MCP clients - such as Codex,
via list_mcp_resources/read_mcp_resource - that can read resources but cannot
call tools on external MCP servers.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

from fastmcp import FastMCP

from adapters.sharedmenn import SharedMENNAdapter
from config import get_settings
from controller.checkpoint import checkpoint as run_checkpoint
from controller.get_context import get_context as run_get_context
from db.events import write_event
from schema import Agent, SessionEvent

logger = logging.getLogger(__name__)

settings = get_settings()
adapter = SharedMENNAdapter(
    base_url=settings.sharedmenn_url,
    token=settings.sharedmenn_token,
    verify_ssl=settings.sharedmenn_verify_ssl,
)

mcp = FastMCP("mennbridge")


async def registered_tool_names() -> list[str]:
    """Return the exact MCP tool names registered on MENNBridge."""
    return [tool.name for tool in await mcp.list_tools()]


async def registered_resource_uris() -> list[str]:
    """Return the exact MCP resource URIs registered on MENNBridge."""
    return [str(resource.uri) for resource in await mcp.list_resources()]

# Set by dashboard/ws.py at startup (Phase 5) so tool calls can push live
# events to the dashboard's Live Feed panel. Kept as an injected hook so
# this module never has to import the dashboard package.
_broadcast_hook: Callable[[SessionEvent], None] | None = None


def set_broadcast_hook(hook: Callable[[SessionEvent], None] | None) -> None:
    global _broadcast_hook
    _broadcast_hook = hook


# Toggled by the dashboard's Pause/Resume manager control (Live Feed panel).
# MENNBridge has no background loop to pause - this just makes the two MCP
# tools refuse to do work while paused.
manager_paused = False


def is_paused() -> bool:
    return manager_paused


def set_paused(value: bool) -> None:
    global manager_paused
    manager_paused = value


async def _log_event(
    project_id: str,
    session_id: str,
    agent: Agent,
    tool: str,
    memory_ids: list[str],
) -> None:
    event = SessionEvent(
        project_id=project_id,
        session_id=session_id,
        agent=agent,
        tool=tool,
        memories_affected=memory_ids,
    )
    try:
        await write_event(event, settings.database_url)
    except Exception:
        logger.exception("failed to write event log for project=%s", project_id)
    if _broadcast_hook is not None:
        try:
            _broadcast_hook(event)
        except Exception:
            logger.exception("broadcast hook failed for project=%s", project_id)


@mcp.tool
async def get_context(session_id: str, agent: Agent) -> str:
    """Call this ONCE at the very start of every agent session, before doing
    any other work on the project. Returns a concise handoff brief covering
    the current state, prior decisions, failed attempts, active bottlenecks,
    the last test run, and the next step a previous agent left off at.
    Always call this first so you don't repeat work or redo decisions
    another agent already made. The project is fixed by this server's own
    MENNBRIDGE_PROJECT configuration - there is no project argument here,
    so there's nothing to guess or infer.
    """
    project_id = settings.mennbridge_project
    if manager_paused:
        return "MENNBridge manager is paused; no context available right now."
    brief, memory_ids = await run_get_context(project_id, adapter)
    await _log_event(project_id, session_id, agent, "get_context", memory_ids)
    return brief


@mcp.tool
async def checkpoint(
    session_id: str,
    agent: Agent,
    summary: str,
    status: str,
    files_changed: list[str],
) -> dict:
    """Call this whenever you: (1) complete a task or phase, (2) hit a
    blocker you can't immediately resolve, or (3) are about to stop working
    or hand off to another agent. Pass a plain-language summary of what
    happened - decisions made, things tried and their outcome, test
    results, blockers, and what should happen next. This call returns
    immediately; memory extraction and storage happen in the background,
    so it is safe to call before ending a session. The project is fixed by
    this server's own MENNBRIDGE_PROJECT configuration.
    """
    project_id = settings.mennbridge_project
    if manager_paused:
        return {"stored": False, "reason": "manager paused"}
    result = await run_checkpoint(
        project_id, session_id, agent, summary, status, files_changed, adapter
    )
    await _log_event(project_id, session_id, agent, "checkpoint", [])
    return result


@mcp.resource(
    "mennbridge://context",
    name="Project Context",
    description="Full handoff brief for the current project",
    mime_type="text/plain",
)
async def context_resource() -> str:
    project_id = settings.mennbridge_project
    brief, _memory_ids = await run_get_context(project_id, adapter)
    return brief


@mcp.resource(
    "mennbridge://memories",
    name="Project Memories",
    description="All stored memories for the current project",
    mime_type="application/json",
)
async def memories_resource() -> str:
    project_id = settings.mennbridge_project
    memories = await adapter.list_all(project_id)
    active = [m.model_dump(mode="json") for m in memories if m.superseded_by is None]
    return json.dumps(active)


@mcp.resource(
    "mennbridge://status",
    name="Project Status",
    description="Current state and next step only",
    mime_type="text/plain",
)
async def status_resource() -> str:
    project_id = settings.mennbridge_project
    current_state_list = await adapter.fetch_by_type(project_id, "current_state", limit=1)
    next_step_list = await adapter.fetch_by_type(project_id, "next_step", limit=1)
    current_state = current_state_list[0].content if current_state_list else "No current state recorded yet."
    next_step = next_step_list[0].content if next_step_list else "Not yet determined."
    return f"CURRENT STATE: {current_state}\nNEXT STEP: {next_step}\n"
