import pytest

from controller.get_context import get_context
from schema import Memory


@pytest.mark.asyncio
async def test_get_context_assembles_brief_with_all_sections(adapter):
    sm, _fake = adapter
    project_id = "mennbridge-v1"

    await sm.store(
        Memory(
            project_id=project_id,
            session_id="s1",
            type="current_state",
            content="Working on conflict detection in pipeline.py",
            agent="claude-code",
        )
    )
    await sm.store(
        Memory(
            project_id=project_id,
            session_id="s1",
            type="next_step",
            content="Implement decay scoring before WebSocket bus",
            agent="claude-code",
        )
    )
    await sm.store(
        Memory(
            project_id=project_id,
            session_id="s1",
            type="decision",
            content="FastAPI chosen over Flask - async support required",
            agent="codex",
        )
    )
    await sm.store(
        Memory(
            project_id=project_id,
            session_id="s1",
            type="bottleneck",
            content="Concurrent ChromaDB writes cause lock contention",
            agent="codex",
        )
    )
    await sm.store(
        Memory(
            project_id=project_id,
            session_id="s1",
            type="failed_attempt",
            content="Local sentence-transformers too slow at recall time",
            agent="claude-code",
        )
    )
    await sm.store(
        Memory(
            project_id=project_id,
            session_id="s1",
            type="test_result",
            content="FAIL: JWT refresh not handling token expiry edge case",
            agent="codex",
        )
    )

    brief, memory_ids = await get_context(project_id, sm)

    assert "CURRENT STATE: Working on conflict detection in pipeline.py" in brief
    assert "DECISIONS MADE:" in brief
    assert "FastAPI chosen over Flask" in brief
    assert "WHAT WAS TRIED AND FAILED:" in brief
    assert "ACTIVE BOTTLENECKS:" in brief
    assert "RECENT TEST RESULTS:" in brief
    assert "NEXT STEP:" in brief
    assert "Implement decay scoring before WebSocket bus" in brief
    assert len(memory_ids) == 6


@pytest.mark.asyncio
async def test_get_context_handles_empty_project(adapter):
    sm, _fake = adapter
    brief, memory_ids = await get_context("empty-project", sm)

    assert "CURRENT STATE: No current state recorded yet." in brief
    assert "NEXT STEP:" in brief
    assert "Not yet determined." in brief
    assert memory_ids == []


@pytest.mark.asyncio
async def test_get_context_excludes_superseded_current_state(adapter):
    sm, _fake = adapter
    project_id = "p1"

    old = Memory(
        project_id=project_id, session_id="s1", type="current_state",
        content="old state", agent="codex",
    )
    await sm.store(old)
    new = Memory(
        project_id=project_id, session_id="s1", type="current_state",
        content="new state", agent="codex",
    )
    await sm.store(new)
    await sm.supersede(old.id, project_id, new.id)

    brief, _ = await get_context(project_id, sm)
    assert "CURRENT STATE: new state" in brief
    assert "old state" not in brief


@pytest.mark.asyncio
async def test_get_context_includes_unrelated_decision_regardless_of_semantic_overlap(adapter):
    sm, _fake = adapter
    project_id = "p1"

    await sm.store(Memory(
        project_id=project_id, session_id="s1", type="decision",
        content="Chose PostgreSQL for the event log instead of MySQL", agent="codex",
    ))
    await sm.store(Memory(
        project_id=project_id, session_id="s1", type="current_state",
        content="Debugging a flaky WebSocket reconnect in the frontend dashboard", agent="claude-code",
    ))

    brief, memory_ids = await get_context(project_id, sm)

    assert "CURRENT STATE: Debugging a flaky WebSocket reconnect in the frontend dashboard" in brief
    assert "DECISIONS MADE:" in brief
    assert "Chose PostgreSQL for the event log instead of MySQL" in brief
