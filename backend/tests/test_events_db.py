"""Integration tests against a real Postgres instance.

Requires TEST_DATABASE_URL to point at a throwaway database with
db/init.sql already applied. Skipped automatically when unset (e.g. in
CI environments without Docker), since this is the one layer that can't
be exercised with an in-memory fake.
"""
import os

import pytest

import db.events as events_module
from db.events import read_agent_status, read_events, write_event
from schema import SessionEvent

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set; skipping Postgres integration tests"
)


@pytest.fixture(autouse=True)
async def _clean_tables():
    events_module._pool = None
    pool = await events_module.get_pool(TEST_DATABASE_URL)
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE event_log, sessions")
    yield
    events_module._pool = None


@pytest.mark.asyncio
async def test_write_and_read_events_round_trip():
    event = SessionEvent(
        project_id="p1",
        session_id="s1",
        agent="claude-code",
        tool="get_context",
        memories_affected=["m1", "m2"],
    )
    await write_event(event, TEST_DATABASE_URL)

    events = await read_events("p1", TEST_DATABASE_URL, limit=10)
    assert len(events) == 1
    assert events[0].id == event.id
    assert events[0].memories_affected == ["m1", "m2"]


@pytest.mark.asyncio
async def test_read_events_scoped_to_project_and_ordered_recent_first():
    for i in range(3):
        await write_event(
            SessionEvent(
                project_id="p1", session_id="s1", agent="codex",
                tool="checkpoint", memories_affected=[f"m{i}"],
            ),
            TEST_DATABASE_URL,
        )
    await write_event(
        SessionEvent(project_id="other", session_id="s2", agent="codex", tool="checkpoint"),
        TEST_DATABASE_URL,
    )

    events = await read_events("p1", TEST_DATABASE_URL, limit=10)
    assert len(events) == 3
    assert events[0].memories_affected == ["m2"]


@pytest.mark.asyncio
async def test_write_event_upserts_session_last_seen():
    await write_event(
        SessionEvent(project_id="p1", session_id="s1", agent="claude-code", tool="get_context"),
        TEST_DATABASE_URL,
    )
    await write_event(
        SessionEvent(project_id="p1", session_id="s1", agent="claude-code", tool="checkpoint"),
        TEST_DATABASE_URL,
    )

    pool = await events_module.get_pool(TEST_DATABASE_URL)
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM sessions WHERE session_id = 's1'")
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_read_agent_status_reports_latest_session_and_memory_count():
    await write_event(
        SessionEvent(
            project_id="p1", session_id="s1", agent="claude-code",
            tool="get_context", memories_affected=["m1", "m2"],
        ),
        TEST_DATABASE_URL,
    )
    await write_event(
        SessionEvent(
            project_id="p1", session_id="s1", agent="claude-code",
            tool="checkpoint", memories_affected=["m3"],
        ),
        TEST_DATABASE_URL,
    )
    await write_event(
        SessionEvent(project_id="p1", session_id="s2", agent="codex", tool="get_context"),
        TEST_DATABASE_URL,
    )

    status = await read_agent_status("p1", TEST_DATABASE_URL)
    by_agent = {row["agent"]: row for row in status}

    assert by_agent["claude-code"]["session_id"] == "s1"
    assert by_agent["claude-code"]["memories_written_this_session"] == 3
    assert by_agent["codex"]["session_id"] == "s2"
    assert by_agent["codex"]["memories_written_this_session"] == 0
