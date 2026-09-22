"""Pydantic data models shared across the MENNBridge backend."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

MemoryType = Literal[
    "decision",
    "progress",
    "bottleneck",
    "failed_attempt",
    "test_result",
    "current_state",
    "next_step",
]

Agent = Literal["claude-code", "codex"]

# Types that never decay and are always returned to future agents.
PERMANENT_TYPES: frozenset[MemoryType] = frozenset({"decision", "failed_attempt"})

# Types for which only one active (non-superseded) memory may exist at a time.
SINGLETON_TYPES: frozenset[MemoryType] = frozenset({"current_state", "next_step"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Memory(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    session_id: str
    type: MemoryType
    content: str
    agent: Agent
    timestamp: datetime = Field(default_factory=_utcnow)
    importance: float = Field(default=1.0, ge=0.0, le=1.0)
    superseded_by: str | None = None

    def model_post_init(self, __context) -> None:
        # decision and failed_attempt never decay: pin importance to 1.0.
        if self.type in PERMANENT_TYPES:
            object.__setattr__(self, "importance", 1.0)


class SessionEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    session_id: str
    agent: Agent
    tool: Literal["get_context", "checkpoint"]
    memories_affected: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=_utcnow)
