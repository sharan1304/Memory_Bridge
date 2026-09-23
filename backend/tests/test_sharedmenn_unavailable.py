"""SharedMENN being unreachable, and the adapter's connection settings."""
import asyncio
import socket

import pytest

from adapters.sharedmenn import SharedMENNAdapter
from controller.checkpoint import checkpoint
from controller.get_context import UNAVAILABLE_BRIEF, get_context
from tests.fake_groq import FakeGroqClient


def _closed_port_url() -> str:
    # Bind to an ephemeral port and release it, so nothing is listening there.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}/mcp"


@pytest.mark.asyncio
async def test_get_context_returns_fallback_brief_when_sharedmenn_unreachable(caplog):
    sm = SharedMENNAdapter(base_url=_closed_port_url(), token="t")

    brief, memory_ids = await get_context("p1", sm)

    assert brief == UNAVAILABLE_BRIEF
    assert memory_ids == []
    assert "SharedMENN unavailable" in caplog.text


@pytest.mark.asyncio
async def test_checkpoint_background_extraction_survives_unreachable_sharedmenn(caplog):
    sm = SharedMENNAdapter(base_url=_closed_port_url(), token="t")
    client = FakeGroqClient(response_json=[{"type": "decision", "content": "chose FastAPI"}])

    result = await checkpoint(
        "p1", "s1", "codex", "we decided on FastAPI", "in_progress", [], sm, groq_client=client,
    )
    assert result["stored"] is True

    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    await asyncio.gather(*pending)

    assert "background memory extraction failed" in caplog.text


def test_adapter_sends_bearer_token_when_set():
    sm = SharedMENNAdapter(base_url="http://x/mcp", token="secret")
    assert sm._headers() == {"Authorization": "Bearer secret"}


def test_adapter_omits_auth_header_without_token():
    sm = SharedMENNAdapter(base_url="http://x/mcp", token="")
    assert sm._headers() == {}


def test_adapter_verifies_ssl_by_default():
    assert SharedMENNAdapter(base_url="http://x/mcp").verify_ssl is True
    assert SharedMENNAdapter(base_url="http://x/mcp", verify_ssl=False).verify_ssl is False
