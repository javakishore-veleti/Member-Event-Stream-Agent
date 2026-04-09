"""QdrantClient implementation of the VectorClient seam.

Pulls qdrant-client lazily so the rest of the package and the test suite
never need it installed. Install with ``pip install ".[vector-qdrant]"``
or run the local stack at ``DevOps/Local/VectorDBs/qdrant`` and point
``VECTOR_URL`` at it.
"""
from __future__ import annotations

from typing import Any, Callable

from .base import VectorHit


class QdrantVectorClient:
    def __init__(
        self,
        *,
        url: str,
        collection: str,
        api_key: str | None = None,
        embedder: Callable[[str], list[float]] | None = None,
        vector_size: int = 384,
    ) -> None:
        try:
            from qdrant_client import QdrantClient  # type: ignore[import-not-found]
            from qdrant_client.http import models as qmodels  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                'qdrant-client not installed. Run `pip install ".[vector-qdrant]"`.',
            ) from exc

        self._client = QdrantClient(url=url, api_key=api_key)
        self._collection = collection
        self._embedder = embedder or _zero_embedder(vector_size)
        self._vector_size = vector_size

    async def search_similar_contexts(
        self,
        *,
        query_text: str,
        member_id: str | None,
        k: int = 5,
    ) -> list[VectorHit]:  # pragma: no cover - exercised at deploy time
        vector = self._embedder(query_text)
        flt = None
        if member_id:
            from qdrant_client.http import models as qmodels

            flt = qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="member_id",
                        match=qmodels.MatchValue(value=member_id),
                    ),
                ],
            )
        results = self._client.search(
            collection_name=self._collection,
            query_vector=vector,
            limit=k,
            query_filter=flt,
        )
        return [
            VectorHit(
                id=str(r.id),
                score=float(r.score),
                member_id=(r.payload or {}).get("member_id"),
                text=str((r.payload or {}).get("text", "")),
                metadata=dict(r.payload or {}),
            )
            for r in results
        ]

    async def upsert_context(
        self,
        *,
        doc_id: str,
        text: str,
        member_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:  # pragma: no cover
        from qdrant_client.http import models as qmodels

        payload = {"text": text, "member_id": member_id, **(metadata or {})}
        self._client.upsert(
            collection_name=self._collection,
            points=[
                qmodels.PointStruct(
                    id=doc_id, vector=self._embedder(text), payload=payload,
                ),
            ],
        )


def _zero_embedder(size: int) -> Callable[[str], list[float]]:
    """Stub embedder for the seam — returns a zero vector.

    Replace at construction time with a real embedding callable
    (sentence-transformers, Vertex AI, OpenAI, ...). The seam keeps the
    embedding choice out of this module so each deployment can pick the
    one that matches its compliance / cost envelope.
    """
    return lambda _text: [0.0] * size
