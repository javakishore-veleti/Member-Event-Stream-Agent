"""WeaviateVectorClient implementation of the VectorClient seam.

Pulls weaviate-client lazily. Install via ``pip install ".[vector-weaviate]"``
or run the local stack at ``DevOps/Local/VectorDBs/weaviate``.
"""
from __future__ import annotations

from typing import Any

from .base import VectorHit


class WeaviateVectorClient:
    def __init__(
        self,
        *,
        url: str,
        collection: str,
        api_key: str | None = None,
    ) -> None:
        try:
            import weaviate  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                'weaviate-client not installed. '
                'Run `pip install ".[vector-weaviate]"`.',
            ) from exc

        if api_key:
            self._client = weaviate.connect_to_weaviate_cloud(
                cluster_url=url,
                auth_credentials=weaviate.classes.init.Auth.api_key(api_key),
            )
        else:
            self._client = weaviate.connect_to_local(
                host=url.replace("http://", "").split(":")[0],
            )
        self._collection_name = collection

    async def search_similar_contexts(
        self,
        *,
        query_text: str,
        member_id: str | None,
        k: int = 5,
    ) -> list[VectorHit]:  # pragma: no cover - exercised at deploy time
        coll = self._client.collections.get(self._collection_name)
        # Weaviate's near_text uses the configured server-side vectorizer
        # so the embedding model lives in the cluster, not in this client.
        filters = None
        if member_id:
            from weaviate.classes.query import Filter

            filters = Filter.by_property("member_id").equal(member_id)
        result = coll.query.near_text(query=query_text, limit=k, filters=filters)
        out: list[VectorHit] = []
        for obj in result.objects:
            props = obj.properties or {}
            out.append(
                VectorHit(
                    id=str(obj.uuid),
                    score=float(obj.metadata.distance or 0.0),
                    member_id=props.get("member_id"),
                    text=str(props.get("text", "")),
                    metadata=dict(props),
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
        coll = self._client.collections.get(self._collection_name)
        coll.data.insert(
            uuid=doc_id,
            properties={"text": text, "member_id": member_id, **(metadata or {})},
        )
