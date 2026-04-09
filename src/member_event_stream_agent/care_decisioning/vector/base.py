"""VectorClient Protocol + typed hits + FakeVectorClient.

Why this seam: vector retrieval gives the LLM grounded examples to reason
over (similar past cases for the same payer / dimension). Each backend
has a different SDK; this Protocol decouples care_decisioning agents
from any one of them so swapping Qdrant for Weaviate is a settings flip,
not a refactor.

Embeddings are the backend's job — implementations either pass the query
text to a colocated embedder (sentence-transformers, Vertex AI text
embeddings, OpenAI, ...) or wrap a managed embedding service. This
module deliberately does not pin an embedder so each deployment can pick
the one that matches its compliance + cost envelope.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class VectorHit:
    """One similar member-context document the agent can lean on."""

    id: str
    score: float
    member_id: str | None = None
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorClient(Protocol):
    """Minimal vector retrieval seam used by AdkEnrichmentAgent."""

    async def search_similar_contexts(
        self,
        *,
        query_text: str,
        member_id: str | None,
        k: int = 5,
    ) -> list[VectorHit]: ...

    async def upsert_context(
        self,
        *,
        doc_id: str,
        text: str,
        member_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...


class FakeVectorClient:
    """In-process VectorClient that hands back queued hits.

    Tests construct it with a list of VectorHit instances and (optionally)
    flag the next call to raise — that exercises the AdkEnrichmentAgent's
    silent fall-back contract.
    """

    def __init__(
        self,
        *,
        hits: list[VectorHit] | None = None,
        raise_on_next: bool = False,
    ) -> None:
        self._hits = list(hits or [])
        self._raise_on_next = raise_on_next
        self.search_calls: list[dict[str, Any]] = []
        self.upsert_calls: list[dict[str, Any]] = []

    async def search_similar_contexts(
        self,
        *,
        query_text: str,
        member_id: str | None,
        k: int = 5,
    ) -> list[VectorHit]:
        self.search_calls.append(
            {"query_text": query_text, "member_id": member_id, "k": k},
        )
        if self._raise_on_next:
            self._raise_on_next = False
            raise RuntimeError("simulated vector backend failure")
        return list(self._hits[:k])

    async def upsert_context(
        self,
        *,
        doc_id: str,
        text: str,
        member_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.upsert_calls.append(
            {
                "doc_id": doc_id,
                "text": text,
                "member_id": member_id,
                "metadata": metadata or {},
            },
        )
