"""MilvusVectorClient implementation of the VectorClient seam.

Pulls pymilvus lazily. Install via ``pip install ".[vector-milvus]"`` or
run the local stack at ``DevOps/Local/VectorDBs/milvus``.
"""
from __future__ import annotations

from typing import Any, Callable

from .base import VectorHit


class MilvusVectorClient:
    def __init__(
        self,
        *,
        url: str,
        collection: str,
        embedder: Callable[[str], list[float]] | None = None,
        vector_size: int = 384,
    ) -> None:
        try:
            from pymilvus import MilvusClient  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                'pymilvus not installed. Run `pip install ".[vector-milvus]"`.',
            ) from exc

        self._client = MilvusClient(uri=url)
        self._collection = collection
        self._embedder = embedder or (lambda _t: [0.0] * vector_size)
        self._vector_size = vector_size

    async def search_similar_contexts(
        self,
        *,
        query_text: str,
        member_id: str | None,
        k: int = 5,
    ) -> list[VectorHit]:  # pragma: no cover
        vector = self._embedder(query_text)
        flt = f'member_id == "{member_id}"' if member_id else None
        res = self._client.search(
            collection_name=self._collection,
            data=[vector],
            limit=k,
            filter=flt,
            output_fields=["text", "member_id"],
        )
        out: list[VectorHit] = []
        for batch in res:
            for hit in batch:
                ent = hit.get("entity", {}) or {}
                out.append(
                    VectorHit(
                        id=str(hit.get("id")),
                        score=float(hit.get("distance", 0.0)),
                        member_id=ent.get("member_id"),
                        text=str(ent.get("text", "")),
                        metadata=dict(ent),
                    ),
                )
        return out

    async def upsert_context(
        self,
        *,
        doc_id: str,
        text: str,
        member_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:  # pragma: no cover
        self._client.upsert(
            collection_name=self._collection,
            data=[
                {
                    "id": doc_id,
                    "vector": self._embedder(text),
                    "text": text,
                    "member_id": member_id or "",
                    **(metadata or {}),
                },
            ],
        )
