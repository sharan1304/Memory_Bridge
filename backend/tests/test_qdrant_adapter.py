"""Qdrant-specific adapter behaviour, and Qdrant being unreachable."""
import asyncio
import socket
import uuid

import pytest

from adapters.qdrant import QdrantAdapter, point_id
from controller.checkpoint import checkpoint
from controller.get_context import UNAVAILABLE_BRIEF, get_context
from schema import Memory
from tests.conftest import fake_embed
from tests.fake_groq import FakeGroqClient


def _mem(type_="progress", content="x", **kwargs) -> Memory:
    return Memory(project_id="p1", session_id="s1", type=type_, content=content, agent="codex", **kwargs)


def test_point_id_keeps_uuids_and_maps_other_ids_deterministically():
    u = str(uuid.uuid4())
    assert point_id(u) == u
    assert point_id("mem_0") == point_id("mem_0")
    assert uuid.UUID(point_id("mem_0"))


@pytest.mark.asyncio
async def test_non_uuid_memory_id_round_trips(adapter):
    sm, _fake = adapter
    await sm.store(_mem(id="mem_0", content="hello"))
    fetched = await sm.get_by_id("mem_0")
    assert fetched.id == "mem_0"
    assert fetched.content == "hello"


@pytest.mark.asyncio
async def test_store_supersedes_previous_active_singleton(adapter):
    sm, fake = adapter
    old = _mem("current_state", "state A")
    new = _mem("current_state", "state B")
    await sm.store(old)
    await sm.store(new)

    assert fake.records[old.id]["superseded_by"] == new.id
    assert [m.content for m in await sm.fetch_by_type("p1", "current_state")] == ["state B"]


@pytest.mark.asyncio
async def test_restoring_existing_singleton_does_not_supersede_itself(adapter):
    sm, fake = adapter
    m = _mem("next_step", "do X")
    await sm.store(m)
    m.importance = 0.5
    await sm.store(m)

    assert fake.records[m.id]["superseded_by"] is None


@pytest.mark.asyncio
async def test_get_is_scoped_to_project(adapter):
    sm, _fake = adapter
    m = _mem()
    await sm.store(m)
    assert await sm.get("other-project", m.id) is None
    assert (await sm.get("p1", m.id)).id == m.id


@pytest.mark.asyncio
async def test_delete_repairs_supersede_chain(adapter):
    sm, fake = adapter
    old = _mem("current_state", "state A")
    new = _mem("current_state", "state B")
    await sm.store(old)
    await sm.store(new)

    await sm.delete("p1", new.id)

    assert new.id not in fake.records
    assert fake.records[old.id]["superseded_by"] is None
    assert [m.content for m in await sm.fetch_by_type("p1", "current_state")] == ["state A"]


@pytest.mark.asyncio
async def test_semantic_search_ranks_by_similarity(adapter):
    sm, _fake = adapter
    await sm.store(_mem(content="postgres connection pool exhausted"))
    await sm.store(_mem(content="frontend button colour tweak"))

    results = await sm.semantic_search("p1", "postgres pool", types=["progress"], top_k=1)
    assert [m.content for m in results] == ["postgres connection pool exhausted"]


def _unreachable_adapter() -> QdrantAdapter:
    # Bind to an ephemeral port and release it, so nothing is listening there.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return QdrantAdapter(url=f"http://127.0.0.1:{port}", embedder=fake_embed)


@pytest.mark.asyncio
async def test_get_context_returns_fallback_brief_when_qdrant_unreachable(caplog):
    brief, memory_ids = await get_context("p1", _unreachable_adapter())

    assert brief == UNAVAILABLE_BRIEF
    assert memory_ids == []
    assert "Memory store unavailable" in caplog.text


@pytest.mark.asyncio
async def test_checkpoint_background_extraction_survives_unreachable_qdrant(caplog):
    client = FakeGroqClient(response_json=[{"type": "decision", "content": "chose FastAPI"}])

    result = await checkpoint(
        "p1", "s1", "codex", "we decided on FastAPI", "in_progress", [],
        _unreachable_adapter(), groq_client=client,
    )
    assert result["stored"] is True

    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    await asyncio.gather(*pending)

    assert "background memory extraction failed" in caplog.text
