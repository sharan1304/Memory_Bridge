import asyncio

import pytest

from controller.checkpoint import has_signal, checkpoint
from tests.fake_groq import FakeGroqClient


@pytest.mark.parametrize("summary", [
    "Fixed the JWT refresh bug",
    "We decided to switch to FastAPI",
    "Tried sentence-transformers locally, it failed",
    "Completed phase 1",
    "next step is decay scoring",
])
def test_has_signal_true_for_keyword_summaries(summary):
    assert has_signal(summary) is True


@pytest.mark.parametrize("summary", [
    "Refactored some variable names",
    "Updated the README wording",
    "",
])
def test_has_signal_false_without_keywords(summary):
    assert has_signal(summary) is False


@pytest.mark.asyncio
async def test_checkpoint_skips_extraction_when_no_signal(adapter):
    sm, fake = adapter
    result = await checkpoint(
        "p1", "s1", "codex", "renamed a variable for clarity", "in_progress", [], sm
    )
    assert result["stored"] is False
    assert fake.records == {}


@pytest.mark.asyncio
async def test_checkpoint_schedules_background_extraction_when_signal_found(adapter):
    sm, fake = adapter
    client = FakeGroqClient(
        response_json=[{"type": "decision", "content": "chose FastAPI over Flask"}]
    )

    result = await checkpoint(
        "p1", "s1", "codex", "we decided on FastAPI, async support required",
        "in_progress", ["main.py"], sm, groq_client=client,
    )
    assert result["stored"] is True

    # checkpoint() must return before the background task finishes.
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    assert pending, "expected a background extraction task to still be pending"
    await asyncio.gather(*pending)

    assert len(fake.records) == 1
