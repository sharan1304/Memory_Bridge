"""The only file in MENNBridge that talks to SharedMENN.

SharedMENN is a real MCP server (FastMCP, streamable-HTTP transport, bearer
auth) - not a REST API. It exposes a fixed set of tools with their own
vocabulary (type: knowledge/insight/flag/correction/consensus, importance:
normal/high/critical, agent_id: one of its configured agents), which doesn't
match MENNBridge's Memory model (type: decision/progress/.../next_step,
importance: float 0-1, agent: claude-code/codex).

To carry MENNBridge's model through unchanged, `remember` accepts a set of
passthrough fields (session_id, superseded_by, external_type, external_agent,
external_importance, record_id) that SharedMENN stores verbatim and never
interprets - see SharedMENN's memory_manager.py. `record_id` lets this
adapter dictate the record id at creation time, so a Memory's id and its
SharedMENN record id are always the same string; every other method here
(get, update, delete, list) relies on that.

Records with no external_type (e.g. SharedMENN's own "project created" seed
memory) aren't MENNBridge records and are filtered out wherever a list of
Memory objects is expected.
"""
from __future__ import annotations

from typing import Any, Iterable

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from schema import Memory, MemoryType

AGENT_TO_SHAREDMENN: dict[str, str] = {
    "claude-code": "anthropic_claude_code",
    "codex": "openai_chatgpt",
}

TYPE_TO_SHAREDMENN: dict[str, str] = {
    "decision": "consensus",
    "progress": "knowledge",
    "bottleneck": "flag",
    "failed_attempt": "correction",
    "test_result": "knowledge",
    "current_state": "knowledge",
    "next_step": "insight",
}


def _importance_to_enum(importance: float) -> str:
    if importance >= 0.8:
        return "critical"
    if importance >= 0.5:
        return "high"
    return "normal"


class SharedMENNAdapter:
    def __init__(self, base_url: str, token: str = ""):
        self.base_url = base_url
        self.token = token

    async def aclose(self) -> None:
        # Each call opens and closes its own MCP session - nothing to hold open.
        pass

    async def _call_tool(self, tool: str, arguments: dict[str, Any]) -> Any:
        async with httpx.AsyncClient(headers={"Authorization": f"Bearer {self.token}"}) as http_client:
            async with streamable_http_client(self.base_url, http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, arguments)
                    if result.is_error:
                        detail = result.content[0].text if result.content else "unknown error"
                        raise RuntimeError(f"SharedMENN tool '{tool}' failed: {detail}")
                    structured = result.structured_content
                    if isinstance(structured, dict) and set(structured) == {"result"}:
                        return structured["result"]
                    return structured

    @staticmethod
    def _from_record(record: dict[str, Any]) -> Memory | None:
        if not record.get("external_type") or not record.get("session_id"):
            return None
        importance = record.get("external_importance")
        return Memory(
            id=record["id"],
            project_id=record["project"],
            session_id=record["session_id"],
            type=record["external_type"],
            content=record.get("raw_content") or record.get("compressed_content", ""),
            agent=record.get("external_agent") or "claude-code",
            timestamp=record["created_at"],
            importance=importance if importance is not None else 1.0,
            superseded_by=record.get("superseded_by"),
        )

    async def create_project(self, project_id: str) -> None:
        await self._call_tool(
            "create_project", {"project": project_id, "agent_id": "anthropic_claude_code"}
        )

    async def store(self, memory: Memory) -> None:
        content = memory.content
        summary = content if len(content) <= 160 else content[:157] + "..."
        await self._call_tool(
            "remember",
            {
                "project": memory.project_id,
                "summary": summary,
                "raw_content": content,
                "compressed_content": content,
                "tags": [memory.type],
                "importance": _importance_to_enum(memory.importance),
                "type": TYPE_TO_SHAREDMENN.get(memory.type, "knowledge"),
                "agent_id": AGENT_TO_SHAREDMENN.get(memory.agent, "anthropic_claude_code"),
                "source_chat": memory.session_id,
                "session_id": memory.session_id,
                "superseded_by": memory.superseded_by,
                "external_type": memory.type,
                "external_agent": memory.agent,
                "external_importance": memory.importance,
                "record_id": memory.id,
            },
        )

    async def _all_records(self, project_id: str) -> list[dict[str, Any]]:
        result = await self._call_tool("list_records", {"project": project_id})
        return result or []

    async def fetch_by_type(self, project_id: str, type: MemoryType, limit: int = 10) -> list[Memory]:
        records = await self._all_records(project_id)
        memories = [m for r in records if (m := self._from_record(r)) is not None and m.type == type]
        active = [m for m in memories if m.superseded_by is None]
        active.sort(key=lambda m: m.timestamp, reverse=True)
        return active[:limit]

    async def semantic_search(
        self,
        project_id: str,
        query: str,
        types: Iterable[MemoryType],
        top_k: int = 6,
    ) -> list[Memory]:
        types_set = set(types)
        records = await self._call_tool(
            "search_records",
            {
                "project": project_id,
                "query": query,
                "agent_id": "anthropic_claude_code",
                "top_k": top_k * 3,
            },
        )
        memories = [m for r in (records or []) if (m := self._from_record(r)) is not None]
        filtered = [m for m in memories if m.type in types_set and m.superseded_by is None]
        return filtered[:top_k]

    async def supersede(self, memory_id: str, project_id: str, superseded_by: str | None) -> None:
        await self._call_tool(
            "update_record",
            {
                "project": project_id,
                "memory_id": memory_id,
                # SharedMENN's update_record treats "" as "clear this field
                # to null" - plain None would be indistinguishable from "the
                # caller didn't mention this field, leave it unchanged".
                "superseded_by": superseded_by if superseded_by is not None else "",
            },
        )

    async def list_all(self, project_id: str) -> list[Memory]:
        records = await self._all_records(project_id)
        return [m for r in records if (m := self._from_record(r)) is not None]

    async def get(self, project_id: str, memory_id: str) -> Memory | None:
        record = await self._call_tool("get_record", {"project": project_id, "memory_id": memory_id})
        if not record:
            return None
        return self._from_record(record)

    async def update_content(self, project_id: str, memory_id: str, content: str) -> Memory | None:
        record = await self._call_tool(
            "update_record",
            {
                "project": project_id,
                "memory_id": memory_id,
                "raw_content": content,
                "compressed_content": content,
            },
        )
        if not record:
            return None
        return self._from_record(record)

    async def delete(self, project_id: str, memory_id: str) -> None:
        await self._call_tool("forget", {"project": project_id, "memory_id": memory_id})
