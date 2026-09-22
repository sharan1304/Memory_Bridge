import asyncio
import threading
from typing import Any

import pytest_asyncio
import uvicorn
from mcp.server.mcpserver import MCPServer

from adapters.sharedmenn import SharedMENNAdapter


class FakeSharedMENN:
    """Stand-in for the real SharedMENN MCP server, run as a real local HTTP
    server so tests exercise the exact same client code path as production.

    Implements just the tool surface SharedMENNAdapter calls, backed by a
    plain dict instead of SharedMENN's real Chroma/embedding stack - good
    enough to exercise the adapter's own logic (id round-tripping, project/
    type filtering, superseding) without depending on the sibling SharedMENN
    project or a real embedding model. No auth check - the adapter still
    sends a bearer token, this fake just doesn't require one.
    """

    def __init__(self):
        self.records: dict[str, dict] = {}
        self.mcp = MCPServer("FakeSharedMENN")
        self._register_tools()

    def _register_tools(self) -> None:
        @self.mcp.tool()
        def create_project(project: str, agent_id: str) -> str:
            return f"Project {project} created. Ready."

        @self.mcp.tool()
        def remember(
            project: str,
            summary: str,
            raw_content: str,
            compressed_content: str,
            tags: list[str],
            importance: str,
            type: str,
            agent_id: str,
            source_chat: str,
            session_id: str | None = None,
            superseded_by: str | None = None,
            external_type: str | None = None,
            external_agent: str | None = None,
            external_importance: float | None = None,
            record_id: str | None = None,
        ) -> dict[str, str]:
            memory_id = record_id or f"mem_{len(self.records)}"
            self.records[memory_id] = {
                "id": memory_id,
                "project": project,
                "raw_content": raw_content,
                "compressed_content": compressed_content,
                "session_id": session_id,
                "superseded_by": superseded_by,
                "external_type": external_type,
                "external_agent": external_agent,
                "external_importance": external_importance,
                "created_at": f"2024-01-01T00:00:{len(self.records):02d}+00:00",
            }
            return {"memory_id": memory_id, "summary": summary}

        @self.mcp.tool()
        def list_records(project: str) -> list[dict[str, Any]]:
            return [r for r in self.records.values() if r["project"] == project]

        @self.mcp.tool()
        def search_records(project: str, query: str, agent_id: str, top_k: int = 5) -> list[dict[str, Any]]:
            return [r for r in self.records.values() if r["project"] == project][:top_k]

        @self.mcp.tool()
        def get_record(project: str, memory_id: str) -> dict[str, Any]:
            record = self.records.get(memory_id)
            if record is None or record["project"] != project:
                return {}
            return record

        @self.mcp.tool()
        def update_record(
            project: str,
            memory_id: str,
            raw_content: str | None = None,
            compressed_content: str | None = None,
            external_type: str | None = None,
            superseded_by: str | None = None,
            external_importance: float | None = None,
        ) -> dict[str, Any]:
            record = self.records.get(memory_id)
            if record is None or record["project"] != project:
                return {}
            if raw_content is not None:
                record["raw_content"] = raw_content
            if compressed_content is not None:
                record["compressed_content"] = compressed_content
            if external_type is not None:
                record["external_type"] = external_type
            if superseded_by is not None:
                # "" means "clear to null" (see adapters/sharedmenn.py's
                # supersede()) - matches the real SharedMENN server's
                # update_record semantics.
                record["superseded_by"] = superseded_by or None
            if external_importance is not None:
                record["external_importance"] = external_importance
            return record

        @self.mcp.tool()
        def forget(project: str, memory_id: str) -> bool:
            record = self.records.get(memory_id)
            if record is None or record["project"] != project:
                return False
            del self.records[memory_id]
            return True


@pytest_asyncio.fixture
async def adapter():
    fake = FakeSharedMENN()
    app = fake.mcp.streamable_http_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)

    # Run the fake server in its own thread (with its own event loop, via
    # uvicorn.Server.run()) rather than as a task on the test's event loop.
    # Some tests (e.g. test_checkpoint) inspect asyncio.all_tasks() to find
    # and await a specific background task - a same-loop server task would
    # show up there too and never finish, hanging that gather() forever.
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]

    try:
        yield SharedMENNAdapter(base_url=f"http://127.0.0.1:{port}/mcp", token="test-token"), fake
    finally:
        server.should_exit = True
        thread.join(timeout=5)
