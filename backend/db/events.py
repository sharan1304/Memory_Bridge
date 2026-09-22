"""Postgres-backed event log: every get_context()/checkpoint() call."""
from __future__ import annotations

import asyncpg

from schema import SessionEvent

_pool: asyncpg.Pool | None = None


async def get_pool(database_url: str) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=database_url)
    return _pool


async def write_event(event: SessionEvent, database_url: str) -> None:
    pool = await get_pool(database_url)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO event_log (id, project_id, session_id, agent, tool, memories_affected, timestamp)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                event.id,
                event.project_id,
                event.session_id,
                event.agent,
                event.tool,
                event.memories_affected,
                event.timestamp,
            )
            await conn.execute(
                """
                INSERT INTO sessions (session_id, project_id, agent, started_at, last_seen)
                VALUES ($1, $2, $3, $4, $4)
                ON CONFLICT (session_id) DO UPDATE SET last_seen = $4
                """,
                event.session_id,
                event.project_id,
                event.agent,
                event.timestamp,
            )


async def read_events(project_id: str, database_url: str, limit: int = 50) -> list[SessionEvent]:
    pool = await get_pool(database_url)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, project_id, session_id, agent, tool, memories_affected, timestamp
            FROM event_log
            WHERE project_id = $1
            ORDER BY timestamp DESC
            LIMIT $2
            """,
            project_id,
            limit,
        )
    return [
        SessionEvent(
            id=str(row["id"]),
            project_id=row["project_id"],
            session_id=row["session_id"],
            agent=row["agent"],
            tool=row["tool"],
            memories_affected=list(row["memories_affected"]),
            timestamp=row["timestamp"],
        )
        for row in rows
    ]


async def read_project_ids(database_url: str) -> list[str]:
    pool = await get_pool(database_url)
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT project_id FROM event_log ORDER BY project_id")
    return [row["project_id"] for row in rows]


async def read_agent_status(project_id: str, database_url: str) -> list[dict]:
    """Latest session and memories-written count per agent, for the
    dashboard's Agent Status panel."""
    pool = await get_pool(database_url)
    async with pool.acquire() as conn:
        session_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (agent) agent, session_id, started_at, last_seen
            FROM sessions
            WHERE project_id = $1
            ORDER BY agent, last_seen DESC
            """,
            project_id,
        )
        count_rows = await conn.fetch(
            """
            SELECT session_id, COALESCE(SUM(COALESCE(array_length(memories_affected, 1), 0)), 0) AS memory_count
            FROM event_log
            WHERE project_id = $1
            GROUP BY session_id
            """,
            project_id,
        )
    counts = {row["session_id"]: row["memory_count"] for row in count_rows}
    return [
        {
            "agent": row["agent"],
            "session_id": row["session_id"],
            "started_at": row["started_at"],
            "last_seen": row["last_seen"],
            "memories_written_this_session": counts.get(row["session_id"], 0),
        }
        for row in session_rows
    ]
