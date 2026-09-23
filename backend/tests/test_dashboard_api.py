"""Dashboard API tests. Uses the same in-memory Qdrant as the adapter tests
(via the `adapter` fixture in conftest.py), and the real test Postgres for
event/agent endpoints (skipped without it).
"""
import os

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

import db.events as events_module
import mcp_server
from schema import Memory

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest_asyncio.fixture
async def dashboard_client(adapter, monkeypatch):
    test_adapter, fake = adapter
    monkeypatch.setattr(mcp_server, "adapter", test_adapter)
    mcp_server.set_paused(False)

    if TEST_DATABASE_URL:
        monkeypatch.setattr("dashboard.api.settings.database_url", TEST_DATABASE_URL)
        events_module._pool = None

    from main import app

    with TestClient(app) as client:
        yield client, test_adapter, fake


def test_memory_crud_lifecycle(dashboard_client):
    client, sm, fake = dashboard_client

    created = client.post(
        "/dashboard/memories",
        json={"project_id": "p1", "type": "decision", "content": "chose FastAPI", "agent": "codex"},
    )
    assert created.status_code == 200
    memory_id = created.json()["id"]

    listed = client.get("/dashboard/memories", params={"project_id": "p1"})
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    fetched = client.get(f"/dashboard/memories/{memory_id}", params={"project_id": "p1"})
    assert fetched.status_code == 200
    assert fetched.json()["content"] == "chose FastAPI"

    patched = client.patch(
        f"/dashboard/memories/{memory_id}", params={"project_id": "p1"}, json={"content": "chose FastAPI, final"}
    )
    assert patched.status_code == 200
    assert patched.json()["content"] == "chose FastAPI, final"

    deleted = client.delete(f"/dashboard/memories/{memory_id}", params={"project_id": "p1"})
    assert deleted.status_code == 200

    missing = client.get(f"/dashboard/memories/{memory_id}", params={"project_id": "p1"})
    assert missing.status_code == 404


def test_create_memory_supersedes_existing_singleton(dashboard_client):
    client, sm, fake = dashboard_client

    first = client.post(
        "/dashboard/memories",
        json={"project_id": "p1", "type": "current_state", "content": "state A", "agent": "codex"},
    )
    second = client.post(
        "/dashboard/memories",
        json={"project_id": "p1", "type": "current_state", "content": "state B", "agent": "codex"},
    )
    assert first.status_code == 200 and second.status_code == 200

    listed = client.get("/dashboard/memories", params={"project_id": "p1"}).json()
    active = [m for m in listed if m["superseded_by"] is None]
    assert len(active) == 1
    assert active[0]["content"] == "state B"


def test_delete_head_of_supersede_chain_repairs_previous_memory(dashboard_client):
    client, sm, fake = dashboard_client
    import asyncio

    from controller.get_context import get_context

    first = client.post(
        "/dashboard/memories",
        json={"project_id": "p1", "type": "current_state", "content": "state A", "agent": "codex"},
    ).json()
    second = client.post(
        "/dashboard/memories",
        json={"project_id": "p1", "type": "current_state", "content": "state B", "agent": "codex"},
    ).json()

    # The second post's singleton handling should already have superseded
    # the first via the create_memory endpoint.
    assert client.get(f"/dashboard/memories/{first['id']}", params={"project_id": "p1"}).json()[
        "superseded_by"
    ] == second["id"]

    deleted = client.delete(f"/dashboard/memories/{second['id']}", params={"project_id": "p1"})
    assert deleted.status_code == 200

    repaired = client.get(f"/dashboard/memories/{first['id']}", params={"project_id": "p1"}).json()
    assert repaired["superseded_by"] is None

    brief, _ = asyncio.run(get_context("p1", sm))
    assert "CURRENT STATE: state A" in brief


def test_manager_pause_blocks_mcp_tools_then_resume_unblocks(dashboard_client):
    client, sm, fake = dashboard_client

    paused = client.post("/dashboard/manager/pause")
    assert paused.status_code == 200
    assert mcp_server.is_paused() is True

    resumed = client.post("/dashboard/manager/resume")
    assert resumed.status_code == 200
    assert mcp_server.is_paused() is False


def test_conflicts_endpoint_flags_similar_decisions(dashboard_client):
    client, sm, fake = dashboard_client
    import asyncio

    asyncio.run(sm.store(Memory(
        project_id="p1", session_id="s1", type="decision",
        content="chose FastAPI over Flask for async support", agent="codex",
    )))
    asyncio.run(sm.store(Memory(
        project_id="p1", session_id="s1", type="decision",
        content="chose FastAPI over Flask for async support and speed", agent="claude-code",
    )))

    resp = client.get("/dashboard/conflicts", params={"project_id": "p1"})
    assert resp.status_code == 200
    conflicts = resp.json()
    assert len(conflicts) == 1


def test_decay_endpoint_excludes_permanent_types_and_sorts_ascending(dashboard_client):
    client, sm, fake = dashboard_client
    import asyncio

    asyncio.run(sm.store(Memory(
        project_id="p1", session_id="s1", type="decision", content="permanent decision", agent="codex",
    )))
    asyncio.run(sm.store(Memory(
        project_id="p1", session_id="s1", type="progress", content="phase 1 done", agent="codex", importance=0.9,
    )))

    resp = client.get("/dashboard/decay", params={"project_id": "p1"})
    assert resp.status_code == 200
    data = resp.json()
    types = [row["memory"]["type"] for row in data]
    assert "decision" not in types
    assert "progress" in types


def test_decay_reinforce_resets_importance(dashboard_client):
    client, sm, fake = dashboard_client
    import asyncio

    m = Memory(
        project_id="p1", session_id="s1", type="progress", content="old progress",
        agent="codex", importance=0.1,
    )
    asyncio.run(sm.store(m))

    resp = client.post(f"/dashboard/decay/{m.id}/reinforce", params={"project_id": "p1"})
    assert resp.status_code == 200
    assert resp.json()["importance"] == 1.0


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set")
def test_events_and_agents_endpoints(dashboard_client):
    client, sm, fake = dashboard_client
    import asyncio

    from db.events import write_event
    from schema import SessionEvent

    async def _seed():
        pool = await events_module.get_pool(TEST_DATABASE_URL)
        async with pool.acquire() as conn:
            await conn.execute("TRUNCATE event_log, sessions")
        await write_event(
            SessionEvent(
                project_id="p1", session_id="s1", agent="claude-code",
                tool="get_context", memories_affected=["m1"],
            ),
            TEST_DATABASE_URL,
        )

    asyncio.run(_seed())
    # _seed() ran its own event loop (asyncio.run); the TestClient below
    # drives the app in a different loop via its anyio portal, so the pool
    # bound to _seed()'s loop must not be reused across the loop boundary.
    events_module._pool = None

    events = client.get("/dashboard/events", params={"project_id": "p1"})
    assert events.status_code == 200
    assert len(events.json()) == 1
    assert events.json()[0]["tool"] == "get_context"

    agents = client.get("/dashboard/agents", params={"project_id": "p1"})
    assert agents.status_code == 200
    agent_rows = agents.json()
    assert agent_rows[0]["agent"] == "claude-code"
    assert agent_rows[0]["memories_written_this_session"] == 1
