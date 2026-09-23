import pytest

from controller.extractor import _parse_items, extract_and_store, items_to_memories
from schema import Memory
from tests.fake_groq import FakeGroqClient


def test_parse_items_plain_json_array():
    items = _parse_items('[{"type": "decision", "content": "chose FastAPI"}]')
    assert items == [{"type": "decision", "content": "chose FastAPI"}]


def test_parse_items_strips_markdown_fence():
    text = '```json\n[{"type": "bottleneck", "content": "lock contention"}]\n```'
    items = _parse_items(text)
    assert items == [{"type": "bottleneck", "content": "lock contention"}]


def test_parse_items_unwraps_dict_wrapped_array():
    text = '{"memories": [{"type": "progress", "content": "phase 1 done"}]}'
    items = _parse_items(text)
    assert items == [{"type": "progress", "content": "phase 1 done"}]


def test_parse_items_returns_empty_on_garbage():
    assert _parse_items("not json at all") == []


def test_items_to_memories_filters_invalid_type_and_missing_content():
    items = [
        {"type": "decision", "content": "chose FastAPI"},
        {"type": "not_a_real_type", "content": "should be dropped"},
        {"type": "progress"},  # missing content
    ]
    memories = items_to_memories(items, "p1", "s1", "codex")
    assert len(memories) == 1
    assert memories[0].type == "decision"


@pytest.mark.asyncio
async def test_extract_and_store_stores_plain_types_directly(adapter):
    sm, fake = adapter
    client = FakeGroqClient(
        response_json=[{"type": "decision", "content": "chose FastAPI over Flask"}]
    )

    memories = await extract_and_store("p1", "s1", "codex", "we decided on FastAPI", sm, client=client)

    assert len(memories) == 1
    assert len(fake.records) == 1
    stored = next(iter(fake.records.values()))
    assert stored["content"] == "chose FastAPI over Flask"
    assert stored["type"] == "decision"


@pytest.mark.asyncio
async def test_extract_and_store_supersedes_existing_current_state(adapter):
    sm, fake = adapter
    old_state = Memory(
        project_id="p1", session_id="s0", type="current_state",
        content="old state", agent="claude-code",
    )
    await sm.store(old_state)

    client = FakeGroqClient(
        response_json=[{"type": "current_state", "content": "new state after fix"}]
    )
    memories = await extract_and_store("p1", "s1", "codex", "fixed the bug, now working on new state", sm, client=client)

    new_state = memories[0]
    assert fake.records[old_state.id]["superseded_by"] == new_state.id
    assert fake.records[new_state.id]["superseded_by"] is None

    active = await sm.fetch_by_type("p1", "current_state", limit=5)
    assert len(active) == 1
    assert active[0].content == "new state after fix"


@pytest.mark.asyncio
async def test_extract_and_store_sends_correct_model_and_temperature(adapter, monkeypatch):
    sm, _fake = adapter
    monkeypatch.setenv("GROQ_MODEL", "llama-3.1-8b-instant")
    from config import get_settings
    get_settings.cache_clear()

    client = FakeGroqClient(response_json=[])
    await extract_and_store("p1", "s1", "codex", "nothing notable happened but fixed a typo", sm, client=client)

    assert client.calls[0]["model"] == "llama-3.1-8b-instant"
    assert client.calls[0]["temperature"] == 0.1
    get_settings.cache_clear()
