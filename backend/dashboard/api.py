"""Dashboard REST API - a query/control interface for the developer, not the agents."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import mcp_server
from config import get_settings
from controller.conflict import find_conflicts
from controller.decay import decay_ranked, reinforce
from db.events import read_agent_status, read_events, read_project_ids
from schema import SINGLETON_TYPES, Agent, Memory, MemoryType

router = APIRouter(prefix="/dashboard")
settings = get_settings()


class MemoryPatch(BaseModel):
    content: str


class MemoryCreate(BaseModel):
    project_id: str
    type: MemoryType
    content: str
    agent: Agent
    session_id: str = "dashboard"


@router.get("/projects")
async def list_projects():
    """Distinct projects this deployment's Postgres has ever logged events
    for - the dashboard's project switcher reads this to populate its
    dropdown. Falls back to this deployment's own configured project when
    event_log is empty (fresh install, nothing has called get_context/
    checkpoint yet)."""
    project_ids = await read_project_ids(settings.database_url)
    if not project_ids:
        project_ids = [settings.mennbridge_project]
    return {"projects": project_ids, "default": settings.mennbridge_project}


@router.get("/memories")
async def list_memories(project_id: str):
    memories = await mcp_server.adapter.list_all(project_id)
    return [m.model_dump(mode="json") for m in memories]


@router.get("/memories/{memory_id}")
async def get_memory(memory_id: str, project_id: str):
    memory = await mcp_server.adapter.get(project_id, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return memory.model_dump(mode="json")


@router.patch("/memories/{memory_id}")
async def patch_memory(memory_id: str, project_id: str, patch: MemoryPatch):
    memory = await mcp_server.adapter.update_content(project_id, memory_id, patch.content)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return memory.model_dump(mode="json")


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str, project_id: str):
    # If this memory is the head of a supersede chain, deleting it would
    # orphan whatever it superseded: that memory would keep pointing at a
    # now-nonexistent id and stay wrongly hidden from get_context() (which
    # treats any non-null superseded_by as "not active"). Repair the chain
    # first by promoting the memory(ies) it superseded back to active.
    all_memories = await mcp_server.adapter.list_all(project_id)
    orphaned = [m for m in all_memories if m.superseded_by == memory_id]
    for orphan in orphaned:
        await mcp_server.adapter.supersede(orphan.id, project_id, None)

    await mcp_server.adapter.delete(project_id, memory_id)
    return {"deleted": memory_id}


@router.post("/memories")
async def create_memory(payload: MemoryCreate):
    memory = Memory(
        project_id=payload.project_id,
        session_id=payload.session_id,
        type=payload.type,
        content=payload.content,
        agent=payload.agent,
    )
    if memory.type in SINGLETON_TYPES:
        existing = await mcp_server.adapter.fetch_by_type(payload.project_id, memory.type, limit=1)
        for old in existing:
            await mcp_server.adapter.supersede(old.id, payload.project_id, memory.id)
    await mcp_server.adapter.store(memory)
    return memory.model_dump(mode="json")


@router.post("/manager/pause")
async def pause_manager():
    mcp_server.set_paused(True)
    return {"paused": True}


@router.post("/manager/resume")
async def resume_manager():
    mcp_server.set_paused(False)
    return {"paused": False}


@router.get("/events")
async def get_events(project_id: str, limit: int = 50):
    events = await read_events(project_id, settings.database_url, limit=limit)
    return [e.model_dump(mode="json") for e in events]


@router.get("/agents")
async def get_agents(project_id: str):
    return await read_agent_status(project_id, settings.database_url)


@router.get("/conflicts")
async def get_conflicts(project_id: str):
    conflicts = await find_conflicts(project_id, mcp_server.adapter)
    return [
        {
            "memory_a": c["memory_a"].model_dump(mode="json"),
            "memory_b": c["memory_b"].model_dump(mode="json"),
            "similarity": c["similarity"],
            "likely_contradiction": c["likely_contradiction"],
        }
        for c in conflicts
    ]


@router.get("/decay")
async def get_decay(project_id: str):
    ranked = await decay_ranked(project_id, mcp_server.adapter)
    return [
        {"memory": r["memory"].model_dump(mode="json"), "importance": r["importance"]}
        for r in ranked
    ]


@router.post("/decay/{memory_id}/reinforce")
async def reinforce_memory(memory_id: str, project_id: str):
    memory = await reinforce(memory_id, project_id, mcp_server.adapter)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return memory.model_dump(mode="json")
