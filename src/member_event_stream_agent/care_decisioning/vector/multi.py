"""MultiVectorClient — fans out upserts and merges searches across backends.

Picked when ``VECTOR_PROVIDER`` lists more than one backend (or the
shorthand ``all``). Upserts go to every member backend; failures on
individual backends are logged and tolerated so a slow backend can
never bring the agent down. Searches concurrently call every member
backend, drop duplicates by id, and return the top-k by best score.
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from .base import VectorClient, VectorHit


class MultiVectorClient:
    def __init__(self, clients: list[tuple[str, VectorClient]]) -> None:
        if not clients:
            raise ValueError("MultiVectorClient requires at least one backend")
        self._clients = clients
        self._log = structlog.get_logger(__name__)

    @property
    def backends(self) -> list[str]:
        return [name for name, _ in self._clients]

    async def search_similar_contexts(
        self,
        *,
        query_text: str,
        member_id: str | None,
        k: int = 5,
    ) -> list[VectorHit]:
        async def _one(name: str, client: VectorClient) -> list[VectorHit]:
            try:
                return await client.search_similar_contexts(
                    query_text=query_text, member_id=member_id, k=k,
                )
            except Exception as exc:  # noqa: BLE001 — tolerate per-backend failures
                self._log.warning(
                    "vector.multi.search_failed", backend=name, error=str(exc),
                )
                return []

        results = await asyncio.gather(
            *(_one(name, c) for name, c in self._clients),
        )
        merged: dict[str, VectorHit] = {}
        for batch in results:
            for hit in batch:
                existing = merged.get(hit.id)
                if existing is None or hit.score > existing.score:
                    merged[hit.id] = hit
        return sorted(merged.values(), key=lambda h: h.score, reverse=True)[:k]

    async def upsert_context(
        self,
        *,
        doc_id: str,
        text: str,
        member_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        async def _one(name: str, client: VectorClient) -> None:
            try:
                await client.upsert_context(
                    doc_id=doc_id,
                    text=text,
                    member_id=member_id,
                    metadata=metadata,
                )
            except Exception as exc:  # noqa: BLE001
                self._log.warning(
                    "vector.multi.upsert_failed", backend=name, error=str(exc),
                )

        await asyncio.gather(*(_one(name, c) for name, c in self._clients))
