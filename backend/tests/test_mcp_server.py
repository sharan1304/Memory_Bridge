import json

import pytest
from fastmcp import Client

import controller.extractor as extractor
import mcp_server
from tests.fake_groq import FakeGroqClient


@pytest.fixture
def wired_mcp(adapter, monkeypatch):
    """Point the module-level adapter at a fake SharedMENN server, and the
    background Groq extraction call at a fake client, so no real network
    traffic ever leaves the test."""
    test_adapter, fake = adapter
    monkeypatch.setattr(mcp_server, "adapter", test_adapter)
    monkeypatch.setattr(mcp_server.settings, "mennbridge_project", "p1")
    monkeypatch.setattr(extractor, "AsyncGroq", lambda **kwargs: FakeGroqClient(response_json=[]))

    async def _noop_log_event(*args, **kwargs):
        return None

    monkeypatch.setattr(mcp_server, "_log_event", _noop_log_event)
    return mcp_server.mcp, fake


@pytest.mark.asyncio
async def test_get_context_tool_is_registered_and_callable(wired_mcp):
    mcp, _fake = wired_mcp
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        assert "get_context" in names
        assert "checkpoint" in names

        result = await client.call_tool(
            "get_context",
            {"session_id": "s1", "agent": "claude-code"},
        )
        text = result.content[0].text
        assert "CURRENT STATE" in text
        assert "NEXT STEP" in text


@pytest.mark.asyncio
async def test_resources_are_registered(wired_mcp):
    mcp, _fake = wired_mcp
    async with Client(mcp) as client:
        resources = await client.list_resources()
        uris = {str(r.uri) for r in resources}
        assert {
            "mennbridge://context",
            "mennbridge://memories",
            "mennbridge://status",
        } <= uris


@pytest.mark.asyncio
async def test_context_resource_matches_get_context_tool(wired_mcp):
    mcp, _fake = wired_mcp
    async with Client(mcp) as client:
        tool_result = await client.call_tool(
            "get_context", {"session_id": "s1", "agent": "claude-code"}
        )
        resource_result = await client.read_resource("mennbridge://context")
        assert resource_result[0].text == tool_result.content[0].text
        assert resource_result[0].mime_type == "text/plain"


@pytest.mark.asyncio
async def test_memories_resource_returns_active_memories_as_json(wired_mcp, adapter):
    mcp, _fake = wired_mcp
    _test_adapter, fake = adapter
    async with Client(mcp) as client:
        # checkpoint stores nothing here (no signal), so seed a memory directly
        # through the fake SharedMENN server the way remember() would.
        fake.records["mem_0"] = {
            "id": "mem_0",
            "project": "p1",
            "raw_content": "decided to use FastAPI",
            "compressed_content": "decided to use FastAPI",
            "session_id": "s1",
            "superseded_by": None,
            "external_type": "decision",
            "external_agent": "claude-code",
            "external_importance": 1.0,
            "created_at": "2024-01-01T00:00:00+00:00",
        }
        resource_result = await client.read_resource("mennbridge://memories")
        assert resource_result[0].mime_type == "application/json"
        data = json.loads(resource_result[0].text)
        assert isinstance(data, list)
        assert any(m["id"] == "mem_0" and m["type"] == "decision" for m in data)


@pytest.mark.asyncio
async def test_status_resource_reports_current_state_and_next_step(wired_mcp):
    mcp, _fake = wired_mcp
    async with Client(mcp) as client:
        resource_result = await client.read_resource("mennbridge://status")
        text = resource_result[0].text
        assert "CURRENT STATE:" in text
        assert "NEXT STEP:" in text
        assert "DECISIONS MADE" not in text


@pytest.mark.asyncio
async def test_checkpoint_tool_reports_whether_it_stored(wired_mcp):
    mcp, _fake = wired_mcp
    async with Client(mcp) as client:
        no_signal = await client.call_tool(
            "checkpoint",
            {
                "session_id": "s1",
                "agent": "codex",
                "summary": "renamed a variable",
                "status": "in_progress",
                "files_changed": ["a.py"],
            },
        )
        data = json.loads(no_signal.content[0].text)
        assert data["stored"] is False

        with_signal = await client.call_tool(
            "checkpoint",
            {
                "session_id": "s1",
                "agent": "codex",
                "summary": "fixed a bug and decided to use FastAPI",
                "status": "done",
                "files_changed": ["a.py"],
            },
        )
        data = json.loads(with_signal.content[0].text)
        assert data["stored"] is True
