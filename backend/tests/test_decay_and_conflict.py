from datetime import datetime, timedelta, timezone

import pytest

from controller.conflict import find_conflicts
from controller.decay import current_importance, decay_ranked, reinforce
from schema import Memory


def test_current_importance_permanent_types_never_decay():
    old = Memory(
        project_id="p1", session_id="s1", type="decision", content="chose FastAPI",
        agent="codex", timestamp=datetime.now(timezone.utc) - timedelta(days=365),
    )
    assert current_importance(old) == 1.0


def test_current_importance_decays_over_time():
    now = datetime.now(timezone.utc)
    fresh = Memory(
        project_id="p1", session_id="s1", type="progress", content="just now",
        agent="codex", timestamp=now, importance=1.0,
    )
    old = Memory(
        project_id="p1", session_id="s1", type="progress", content="two half-lives ago",
        agent="codex", timestamp=now - timedelta(days=28), importance=1.0,
    )
    assert current_importance(fresh, now) > current_importance(old, now)
    assert current_importance(old, now) == pytest.approx(0.25, abs=0.01)


@pytest.mark.asyncio
async def test_decay_ranked_excludes_permanent_and_superseded(adapter):
    sm, _fake = adapter
    permanent = Memory(project_id="p1", session_id="s1", type="failed_attempt", content="tried X", agent="codex")
    await sm.store(permanent)

    old_state = Memory(project_id="p1", session_id="s1", type="current_state", content="old", agent="codex")
    await sm.store(old_state)
    new_state = Memory(project_id="p1", session_id="s1", type="current_state", content="new", agent="codex")
    await sm.store(new_state)
    await sm.supersede(old_state.id, "p1", new_state.id)

    ranked = await decay_ranked("p1", sm)
    ids = [r["memory"].id for r in ranked]
    assert permanent.id not in ids
    assert old_state.id not in ids
    assert new_state.id in ids


@pytest.mark.asyncio
async def test_reinforce_resets_importance_to_one(adapter):
    sm, _fake = adapter
    m = Memory(project_id="p1", session_id="s1", type="progress", content="stale", agent="codex", importance=0.1)
    await sm.store(m)

    reinforced = await reinforce(m.id, "p1", sm)
    assert reinforced.importance == 1.0

    fetched = await sm.get("p1", m.id)
    assert fetched.importance == 1.0


@pytest.mark.asyncio
async def test_find_conflicts_flags_similar_same_type_memories(adapter):
    sm, _fake = adapter
    await sm.store(Memory(
        project_id="p1", session_id="s1", type="decision",
        content="chose FastAPI over Flask for async support", agent="codex",
    ))
    await sm.store(Memory(
        project_id="p1", session_id="s1", type="decision",
        content="chose FastAPI over Flask for async support and speed", agent="claude-code",
    ))
    await sm.store(Memory(
        project_id="p1", session_id="s1", type="bottleneck",
        content="totally unrelated bottleneck about disk IO", agent="codex",
    ))

    conflicts = await find_conflicts("p1", sm)
    assert len(conflicts) == 1
    assert conflicts[0]["memory_a"].type == "decision"
    assert conflicts[0]["similarity"] >= 0.75


@pytest.mark.asyncio
async def test_find_conflicts_ignores_different_topics_at_low_similarity(adapter):
    sm, _fake = adapter
    await sm.store(Memory(
        project_id="p1", session_id="s1", type="decision",
        content="chose FastAPI over Flask for async support", agent="codex",
    ))
    await sm.store(Memory(
        project_id="p1", session_id="s1", type="decision",
        content="decided to use PostgreSQL instead of MongoDB for structured data", agent="claude-code",
    ))

    conflicts = await find_conflicts("p1", sm)
    assert conflicts == []


@pytest.mark.asyncio
async def test_find_conflicts_flags_same_topic_contradiction_at_high_similarity(adapter):
    sm, _fake = adapter
    await sm.store(Memory(
        project_id="p1", session_id="s1", type="decision",
        content="Switched the auth provider from Auth0 to Clerk", agent="codex",
    ))
    await sm.store(Memory(
        project_id="p1", session_id="s1", type="decision",
        content="Switched the auth provider from Auth0 to Firebase", agent="claude-code",
    ))

    conflicts = await find_conflicts("p1", sm)
    assert len(conflicts) == 1
    assert conflicts[0]["similarity"] >= 0.75
    assert conflicts[0]["likely_contradiction"] is True


@pytest.mark.asyncio
async def test_find_conflicts_never_flags_across_types_even_at_identical_content(adapter):
    sm, _fake = adapter
    await sm.store(Memory(
        project_id="p1", session_id="s1", type="decision",
        content="Same exact wording on purpose", agent="codex",
    ))
    await sm.store(Memory(
        project_id="p1", session_id="s1", type="test_result",
        content="Same exact wording on purpose", agent="claude-code",
    ))

    conflicts = await find_conflicts("p1", sm)
    assert conflicts == []


@pytest.mark.asyncio
async def test_find_conflicts_ignores_different_types_and_identical_content(adapter):
    sm, _fake = adapter
    await sm.store(Memory(project_id="p1", session_id="s1", type="decision", content="same text", agent="codex"))
    await sm.store(Memory(project_id="p1", session_id="s1", type="decision", content="same text", agent="codex"))
    await sm.store(Memory(project_id="p1", session_id="s1", type="bottleneck", content="same text", agent="codex"))

    conflicts = await find_conflicts("p1", sm)
    assert conflicts == []
