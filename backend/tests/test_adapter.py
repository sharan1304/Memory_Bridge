import pytest

from schema import Memory


@pytest.mark.asyncio
async def test_store_and_fetch_by_type(adapter):
    sm, _fake = adapter
    m = Memory(
        project_id="p1",
        session_id="s1",
        type="decision",
        content="chose FastAPI over Flask",
        agent="claude-code",
    )
    await sm.store(m)

    fetched = await sm.fetch_by_type("p1", "decision", limit=5)
    assert len(fetched) == 1
    assert fetched[0].content == "chose FastAPI over Flask"
    assert fetched[0].id == m.id


@pytest.mark.asyncio
async def test_fetch_by_type_returns_most_recent_first_and_respects_limit(adapter):
    sm, _fake = adapter
    for i in range(3):
        await sm.store(
            Memory(
                project_id="p1",
                session_id="s1",
                type="progress",
                content=f"phase {i} done",
                agent="codex",
            )
        )

    fetched = await sm.fetch_by_type("p1", "progress", limit=2)
    assert len(fetched) == 2
    # most recent (last stored) should come first
    assert fetched[0].content == "phase 2 done"


@pytest.mark.asyncio
async def test_fetch_by_type_excludes_superseded(adapter):
    sm, _fake = adapter
    old = Memory(
        project_id="p1",
        session_id="s1",
        type="current_state",
        content="working on X",
        agent="claude-code",
    )
    await sm.store(old)
    new = Memory(
        project_id="p1",
        session_id="s1",
        type="current_state",
        content="working on Y",
        agent="claude-code",
    )
    await sm.store(new)
    await sm.supersede(old.id, "p1", new.id)

    fetched = await sm.fetch_by_type("p1", "current_state", limit=5)
    assert len(fetched) == 1
    assert fetched[0].content == "working on Y"


@pytest.mark.asyncio
async def test_semantic_search_filters_by_type_and_project(adapter):
    sm, _fake = adapter
    await sm.store(
        Memory(
            project_id="p1",
            session_id="s1",
            type="bottleneck",
            content="lock contention on writes",
            agent="codex",
        )
    )
    await sm.store(
        Memory(
            project_id="p1",
            session_id="s1",
            type="progress",
            content="finished phase 1",
            agent="codex",
        )
    )
    await sm.store(
        Memory(
            project_id="other-project",
            session_id="s2",
            type="bottleneck",
            content="unrelated project bottleneck",
            agent="codex",
        )
    )

    results = await sm.semantic_search(
        "p1", query="lock contention", types=["bottleneck", "decision"], top_k=6
    )
    assert len(results) == 1
    assert results[0].content == "lock contention on writes"


@pytest.mark.asyncio
async def test_supersede_sets_superseded_by(adapter):
    sm, fake = adapter
    m = Memory(
        project_id="p1",
        session_id="s1",
        type="next_step",
        content="implement decay scoring",
        agent="claude-code",
    )
    await sm.store(m)
    await sm.supersede(m.id, "p1", "new-id-123")

    stored = fake.records[m.id]
    assert stored["superseded_by"] == "new-id-123"


@pytest.mark.asyncio
async def test_list_all_returns_every_memory_for_project(adapter):
    sm, _fake = adapter
    await sm.store(Memory(project_id="p1", session_id="s1", type="progress", content="a", agent="codex"))
    await sm.store(Memory(project_id="p1", session_id="s1", type="decision", content="b", agent="codex"))
    await sm.store(Memory(project_id="p2", session_id="s1", type="decision", content="c", agent="codex"))

    all_p1 = await sm.list_all("p1")
    assert {m.content for m in all_p1} == {"a", "b"}


@pytest.mark.asyncio
async def test_get_returns_none_for_missing_memory(adapter):
    sm, _fake = adapter
    assert await sm.get("p1", "does-not-exist") is None


@pytest.mark.asyncio
async def test_update_content_rewrites_memory_and_get_reflects_it(adapter):
    sm, _fake = adapter
    m = Memory(project_id="p1", session_id="s1", type="progress", content="old text", agent="codex")
    await sm.store(m)

    updated = await sm.update_content("p1", m.id, "new text")
    assert updated.content == "new text"

    fetched = await sm.get("p1", m.id)
    assert fetched.content == "new text"


@pytest.mark.asyncio
async def test_delete_removes_memory(adapter):
    sm, fake = adapter
    m = Memory(project_id="p1", session_id="s1", type="progress", content="temp", agent="codex")
    await sm.store(m)
    assert m.id in fake.records

    await sm.delete("p1", m.id)
    assert m.id not in fake.records
    assert await sm.get("p1", m.id) is None
