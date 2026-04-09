"""Factory that picks one or more vector backends from Settings.

Supports comma-separated VECTOR_PROVIDER values plus the shorthand
``all`` (== every real backend). When more than one is requested the
factory wraps them in a MultiVectorClient that fans out upserts to every
backend and merges searches across them.

Examples
--------
    VECTOR_PROVIDER=stub                          -> FakeVectorClient
    VECTOR_PROVIDER=qdrant                        -> QdrantVectorClient
    VECTOR_PROVIDER=qdrant,weaviate               -> MultiVectorClient([qdrant, weaviate])
    VECTOR_PROVIDER=all                           -> MultiVectorClient over every real backend
"""
from __future__ import annotations

from typing import Any

from ...config import Settings, get_settings
from .base import FakeVectorClient, VectorClient
from .multi import MultiVectorClient

_REAL_PROVIDERS: tuple[str, ...] = (
    "qdrant",
    "weaviate",
    "chroma",
    "milvus",
    "pgvector",
)


def _parse_providers(raw: str) -> list[str]:
    items = [p.strip().lower() for p in (raw or "").split(",") if p.strip()]
    if not items:
        return ["stub"]
    if "all" in items:
        return list(_REAL_PROVIDERS)
    return items


def _build_one(name: str, settings: Settings) -> VectorClient:
    if name == "stub":
        return FakeVectorClient()
    if name == "qdrant":
        from .qdrant_client import QdrantVectorClient

        return QdrantVectorClient(
            url=settings.vector_url,
            collection=settings.vector_collection,
            api_key=settings.vector_api_key or None,
        )
    if name == "weaviate":
        from .weaviate_client import WeaviateVectorClient

        return WeaviateVectorClient(
            url=settings.vector_url,
            collection=settings.vector_collection,
            api_key=settings.vector_api_key or None,
        )
    if name == "chroma":
        from .chroma_client import ChromaVectorClient

        return ChromaVectorClient(
            url=settings.vector_url, collection=settings.vector_collection,
        )
    if name == "milvus":
        from .milvus_client import MilvusVectorClient

        return MilvusVectorClient(
            url=settings.vector_url, collection=settings.vector_collection,
        )
    if name == "pgvector":
        from .pgvector_client import PgVectorVectorClient

        return PgVectorVectorClient(
            url=settings.vector_url, collection=settings.vector_collection,
        )
    raise ValueError(
        f"unknown VECTOR_PROVIDER entry: {name!r}; "
        f"expected stub | all | one of {_REAL_PROVIDERS}",
    )


def build_vector_client(settings: Settings | None = None) -> VectorClient:
    settings = settings or get_settings()
    providers = _parse_providers(settings.vector_provider)
    if len(providers) == 1:
        return _build_one(providers[0], settings)

    members: list[tuple[str, VectorClient]] = []
    errors: list[str] = []
    for name in providers:
        try:
            members.append((name, _build_one(name, settings)))
        except Exception as exc:  # noqa: BLE001 — tolerate one bad backend
            errors.append(f"{name}: {exc}")
    if not members:
        raise RuntimeError(
            "no vector backends could be constructed: " + "; ".join(errors),
        )
    return MultiVectorClient(members)


def parse_providers(raw: str) -> list[str]:
    """Public helper exposed for tests + tooling."""
    return _parse_providers(raw)
