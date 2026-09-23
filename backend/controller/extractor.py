"""Groq + Llama structured-memory extraction, invoked from checkpoint()."""
from __future__ import annotations

import json
import re
from typing import Any, get_args

from groq import AsyncGroq

from adapters.qdrant import QdrantAdapter
from config import get_settings
from schema import SINGLETON_TYPES, Agent, Memory, MemoryType

VALID_TYPES = frozenset(get_args(MemoryType))

SYSTEM_PROMPT = (
    "You are a development memory extractor. Extract ALL notable "
    "facts from this development update as structured memories.\n\n"
    "Be aggressive — if something happened, extract it.\n"
    "Return a JSON object with key 'memories' containing an array.\n"
    'Each item: {"type": "<type>", "content": "<one sentence>"}\n\n'
    "Valid types and when to use them:\n"
    "- current_state: what is being worked on RIGHT NOW\n"
    "- next_step: what should be done next\n"
    "- decision: any technical or architectural choice made\n"
    "- failed_attempt: anything that did not work or was rejected\n"
    "- bottleneck: any blocker, slowdown, or unresolved problem\n"
    "- test_result: any test pass, fail, or verification result\n"
    "- progress: any task, phase, or milestone completed\n\n"
    "Rules:\n"
    "- Extract AT LEAST current_state from every summary\n"
    "- Extract next_step if any forward intent is mentioned\n"
    "- Never return an empty array if the summary has any content\n"
    "- One sentence per content field, factual and specific\n"
    "- Return ONLY the JSON object, no markdown, no explanation"
)

# If Groq still returns nothing usable for a summary substantial enough to
# clearly contain content, force-extract a minimal current_state memory
# rather than silently losing the checkpoint entirely.
FALLBACK_MIN_WORDS = 20

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_items(raw_text: str) -> list[dict[str, Any]]:
    cleaned = _FENCE_RE.sub("", raw_text).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return []

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                return value
    return []


async def call_groq_extraction(summary: str, client: AsyncGroq | None = None) -> list[dict[str, Any]]:
    settings = get_settings()
    client = client or AsyncGroq(api_key=settings.groq_api_key)
    response = await client.chat.completions.create(
        model=settings.groq_model,
        temperature=0.1,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": summary},
        ],
    )
    return _parse_items(response.choices[0].message.content or "")


def items_to_memories(
    items: list[dict[str, Any]],
    project_id: str,
    session_id: str,
    agent: Agent,
) -> list[Memory]:
    memories = []
    for item in items:
        type_ = item.get("type")
        content = item.get("content")
        if type_ not in VALID_TYPES or not content:
            continue
        memories.append(
            Memory(
                project_id=project_id,
                session_id=session_id,
                agent=agent,
                type=type_,
                content=content,
            )
        )
    return memories


async def extract_and_store(
    project_id: str,
    session_id: str,
    agent: Agent,
    summary: str,
    adapter: QdrantAdapter,
    client: AsyncGroq | None = None,
) -> list[Memory]:
    items = await call_groq_extraction(summary, client=client)
    memories = items_to_memories(items, project_id, session_id, agent)

    if not memories and len(summary.split()) > FALLBACK_MIN_WORDS:
        memories = [
            Memory(
                project_id=project_id,
                session_id=session_id,
                agent=agent,
                type="current_state",
                content=summary,
            )
        ]

    for memory in memories:
        if memory.type in SINGLETON_TYPES:
            existing = await adapter.fetch_by_type(project_id, memory.type, limit=1)
            for old in existing:
                await adapter.supersede(old.id, project_id, memory.id)
        await adapter.store(memory)

    return memories
