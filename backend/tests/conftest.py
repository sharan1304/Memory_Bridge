import hashlib
import math
import re
from typing import Sequence

import pytest_asyncio
from qdrant_client import AsyncQdrantClient

from adapters.qdrant import VECTOR_SIZE, QdrantAdapter

COLLECTION = "test-mennbridge"


def fake_embed(texts: Sequence[str]) -> list[list[float]]:
    """Deterministic bag-of-words embedding: each word hashes into one of
    VECTOR_SIZE buckets. Texts sharing words land close together, which is
    all the tests need - and no 90MB model download."""
    vectors = []
    for text in texts:
        vec = [0.0] * VECTOR_SIZE
        for word in re.findall(r"\w+", text.lower()):
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % VECTOR_SIZE] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        vectors.append([v / norm for v in vec])
    return vectors


class FakeQdrant:
    """Qdrant's own in-memory local mode (real filter/search semantics, no
    server), plus a synchronous `records` view keyed by memory id so tests
    can inspect what was stored."""

    def __init__(self):
        self.client = AsyncQdrantClient(location=":memory:")

    @property
    def records(self) -> dict[str, dict]:
        collections = self.client._client.collections  # local-mode internals
        if COLLECTION not in collections:
            return {}
        points, _ = collections[COLLECTION].scroll(limit=1_000_000, with_payload=True)
        return {p.payload["id"]: p.payload for p in points}


@pytest_asyncio.fixture
async def adapter():
    fake = FakeQdrant()
    yield QdrantAdapter(collection=COLLECTION, client=fake.client, embedder=fake_embed), fake
    await fake.client.close()
