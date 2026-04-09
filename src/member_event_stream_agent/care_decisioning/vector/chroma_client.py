"""ChromaVectorClient implementation of the VectorClient seam.

Pulls chromadb lazily. Install via ``pip install ".[vector-chroma]"`` or
run the local stack at ``DevOps/Local/VectorDBs/chroma``.
"""
from __future__ import annotations

from typing import Any, Callable

from .base import VectorHit


class ChromaVectorClient:
    def __init__(
        self,
        *,
        url: str,
        collection: str,
        embedder: Callable[[str], list[float]] | None = None,
    ) -> None:
        try:
            import chromadb  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                'chromadb not installed. Run `pip install ".[vector-chroma]"`.',
            ) from exc

        host = url.replace("http://", "").replace("https://", "")
        host_only, _, port = host.partition(":")
        self._client = chromadb.HttpClient(
            host=host_only or "localhost", port=int(port or 8000),
        )
        self._collection = self._client.get_or_create_collection(name=collection)
        self._embedder = embedder

    async def search_similar_contexts(
        self,
        *,
        query_text: str,
        member_id: str | None,
        k: int = 5,
    ) -> list[VectorHit]:  # pragma: no cover
        where = {"member_id": member_id} if member_id else None
        kwargs: dict[str, Any] = {"n_results": k, "where": where}
        if self._embedder is not None:
            kwargs["query_embeddings"] = [self._embedder(query_text)]
        else:
            kwargs["query_texts"] = [query_text]
        res = self._collection.query(**kwargs)
        ids = res.get("ids", [[]])[0]
        distances = res.get("distances", [[0.0] * len(ids)])[0]
        documents = res.get("documents", [[""] * len(ids)])[0]
        metadatas = res.get("metadatas", [[{}] * len(ids)])[0]
        out: list[VectorHit] = []
        for i, doc_id in enumerate(ids):
            md = metadatas[i] or {}
            out.append(
                VectorHit(
                    id=str(doc_id),
                    score=float(distances[i]),
                    member_id=md.get("member_id"),
                    text=str(documents[i]),
                    metadata=dict(md),
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
        md = {"member_id": member_id, **(metadata or {})}
        kwargs: dict[str, Any] = {
            "ids": [doc_id],
            "documents": [text],
            "metadatas": [md],
        }
        if self._embedder is not None:
            kwargs["embeddings"] = [self._embedder(text)]
        self._collection.upsert(**kwargs)
