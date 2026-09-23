"""The only file in MENNBridge that talks to the memory store (Qdrant).

Each Memory is one Qdrant point: the vector is an all-MiniLM-L6-v2
embedding of its content, and the payload carries every Memory field
verbatim, so a point round-trips to the exact same Memory.

Qdrant point ids must be UUIDs (or unsigned ints). Memory ids are UUID4
strings by default, and are used as the point id unchanged; any other id
string is mapped to a deterministic uuid5, and the original id is always
kept in the payload's "id" field.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Iterable, Sequence

from qdrant_client import AsyncQdrantClient, models

from schema import SINGLETON_TYPES, Memory, MemoryType

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
VECTOR_SIZE = 384

# Namespace for mapping non-UUID memory ids to point ids.
_ID_NAMESPACE = uuid.UUID("6f1c7f0e-8a0b-4d8e-9a55-6c2b1f9d3e70")

# Payload fields that are filtered on. Qdrant Cloud clusters run in strict
# mode by default, which rejects filters on unindexed payload fields.
_INDEXED_FIELDS = ("project_id", "type", "superseded_by")

_SCROLL_PAGE = 256

# The client's 5s default is too short for the first request after a restart
# on TLS-inspecting corporate networks. qdrant-client takes a single integer
# applied to connect and read alike (and sent as the server-side query
# timeout), so there's no separate connect timeout.
TIMEOUT_SECONDS = 60

Embedder = Callable[[Sequence[str]], list[list[float]]]


def point_id(memory_id: str) -> str:
    try:
        return str(uuid.UUID(memory_id))
    except ValueError:
        return str(uuid.uuid5(_ID_NAMESPACE, memory_id))


def _sentence_transformer_embedder() -> Embedder:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBEDDING_MODEL)

    def embed(texts: Sequence[str]) -> list[list[float]]:
        return model.encode(list(texts), normalize_embeddings=True).tolist()

    return embed


def _match(key: str, value: Any) -> models.FieldCondition:
    return models.FieldCondition(key=key, match=models.MatchValue(value=value))


_ACTIVE = models.IsNullCondition(is_null=models.PayloadField(key="superseded_by"))


class QdrantAdapter:
    def __init__(
        self,
        url: str = "",
        api_key: str = "",
        collection: str = "mennbridge",
        client: AsyncQdrantClient | None = None,
        embedder: Embedder | None = None,
    ):
        self.url = url
        self.collection = collection
        # check_compatibility would make a blocking request to the server at
        # construction time, i.e. when mcp_server is imported.
        self.client = client or AsyncQdrantClient(
            url=url, api_key=api_key or None, check_compatibility=False, timeout=TIMEOUT_SECONDS
        )
        self._embedder = embedder
        self._collection_ready = False

    async def warmup(self) -> None:
        """Load the embedding model and ensure the collection exists, so the
        first get_context/checkpoint call doesn't pay for either."""
        await self._embed_one("warmup")
        await self._ensure_collection()

    async def aclose(self) -> None:
        await self.client.close()

    async def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self._embedder is None:
            # Loaded once and reused; loading and encoding are CPU-bound, so
            # both run off the event loop.
            self._embedder = await asyncio.to_thread(_sentence_transformer_embedder)
        return await asyncio.to_thread(self._embedder, texts)

    async def _embed_one(self, text: str) -> list[float]:
        return (await self._embed([text]))[0]

    async def _ensure_collection(self) -> None:
        if self._collection_ready:
            return
        if not await self.client.collection_exists(self.collection):
            try:
                await self.client.create_collection(
                    self.collection,
                    vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
                )
            except Exception:
                # Lost a creation race with another worker - fine if it exists now.
                if not await self.client.collection_exists(self.collection):
                    raise
            for field in _INDEXED_FIELDS:
                await self.client.create_payload_index(
                    self.collection, field_name=field, field_schema=models.PayloadSchemaType.KEYWORD
                )
        self._collection_ready = True

    @staticmethod
    def _to_payload(memory: Memory) -> dict[str, Any]:
        return memory.model_dump(mode="json")

    @staticmethod
    def _from_payload(payload: dict[str, Any] | None) -> Memory | None:
        if not payload:
            return None
        return Memory.model_validate(payload)

    async def _scroll(self, conditions: list[models.Condition]) -> list[Memory]:
        await self._ensure_collection()
        memories: list[Memory] = []
        offset = None
        while True:
            points, offset = await self.client.scroll(
                self.collection,
                scroll_filter=models.Filter(must=conditions),
                limit=_SCROLL_PAGE,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            memories += [m for p in points if (m := self._from_payload(p.payload)) is not None]
            if offset is None:
                return memories

    async def store(self, memory: Memory) -> None:
        await self._ensure_collection()
        is_new = await self.get_by_id(memory.id) is None
        if is_new and memory.type in SINGLETON_TYPES and memory.superseded_by is None:
            # Only one active current_state / next_step per project.
            for old in await self.fetch_by_type(memory.project_id, memory.type, limit=_SCROLL_PAGE):
                await self.supersede(old.id, memory.project_id, memory.id)
        vector = await self._embed_one(memory.content)
        await self.client.upsert(
            self.collection,
            points=[models.PointStruct(id=point_id(memory.id), vector=vector, payload=self._to_payload(memory))],
        )

    async def fetch_by_type(self, project_id: str, type: MemoryType, limit: int = 10) -> list[Memory]:
        active = await self._scroll([_match("project_id", project_id), _match("type", type), _ACTIVE])
        active.sort(key=lambda m: m.timestamp, reverse=True)
        return active[:limit]

    async def semantic_search(
        self,
        project_id: str,
        query: str,
        types: Iterable[MemoryType],
        top_k: int = 6,
    ) -> list[Memory]:
        await self._ensure_collection()
        vector = await self._embed_one(query)
        response = await self.client.query_points(
            self.collection,
            query=vector,
            query_filter=models.Filter(
                must=[
                    _match("project_id", project_id),
                    models.FieldCondition(key="type", match=models.MatchAny(any=list(types))),
                    _ACTIVE,
                ]
            ),
            limit=top_k,
            with_payload=True,
        )
        return [m for p in response.points if (m := self._from_payload(p.payload)) is not None]

    async def supersede(self, memory_id: str, project_id: str, superseded_by: str | None) -> None:
        memory = await self.get(project_id, memory_id)
        if memory is None:
            return
        await self.client.set_payload(
            self.collection, payload={"superseded_by": superseded_by}, points=[point_id(memory_id)]
        )

    async def list_all(self, project_id: str) -> list[Memory]:
        """Every memory in the project, superseded ones included - the
        dashboard shows supersede history; callers filter for active."""
        return await self._scroll([_match("project_id", project_id)])

    async def get_by_id(self, memory_id: str) -> Memory | None:
        await self._ensure_collection()
        points = await self.client.retrieve(
            self.collection, ids=[point_id(memory_id)], with_payload=True, with_vectors=False
        )
        return self._from_payload(points[0].payload) if points else None

    async def get(self, project_id: str, memory_id: str) -> Memory | None:
        memory = await self.get_by_id(memory_id)
        if memory is None or memory.project_id != project_id:
            return None
        return memory

    async def update_content(self, project_id: str, memory_id: str, content: str) -> Memory | None:
        memory = await self.get(project_id, memory_id)
        if memory is None:
            return None
        memory.content = content
        await self.store(memory)
        return memory

    async def repair_supersede_chain(self, deleted_id: str) -> None:
        """Reactivate whatever `deleted_id` superseded, so deleting the head of
        a chain doesn't leave its predecessor pointing at a missing id."""
        for orphan in await self._scroll([_match("superseded_by", deleted_id)]):
            await self.client.set_payload(
                self.collection, payload={"superseded_by": None}, points=[point_id(orphan.id)]
            )

    async def delete(self, project_id: str, memory_id: str) -> None:
        if await self.get(project_id, memory_id) is None:
            return
        await self.repair_supersede_chain(memory_id)
        await self.client.delete(
            self.collection, points_selector=models.PointIdsList(points=[point_id(memory_id)])
        )
