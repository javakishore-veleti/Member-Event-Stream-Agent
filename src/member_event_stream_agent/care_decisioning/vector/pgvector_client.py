"""PgVectorVectorClient implementation of the VectorClient seam.

Pulls psycopg lazily and assumes the pgvector extension is installed in
the target database. Install via ``pip install ".[vector-pgvector]"`` or
run the local stack at ``DevOps/Local/VectorDBs/pgvector``.

Schema (created on first use):

    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE TABLE IF NOT EXISTS <table> (
        id TEXT PRIMARY KEY,
        member_id TEXT,
        text TEXT,
        metadata JSONB,
        embedding vector(<dim>)
    );
    CREATE INDEX IF NOT EXISTS ... ON <table> USING ivfflat (embedding vector_cosine_ops);
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .base import VectorHit


class PgVectorVectorClient:
    def __init__(
        self,
        *,
        url: str,
        collection: str,
        embedder: Callable[[str], list[float]] | None = None,
        vector_size: int = 384,
    ) -> None:
        try:
            import psycopg  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                'psycopg not installed. Run `pip install ".[vector-pgvector]"`.',
            ) from exc

        self._psycopg = psycopg
        self._dsn = url
        self._table = collection
        self._vector_size = vector_size
        self._embedder = embedder or (lambda _t: [0.0] * vector_size)
        self._ensure_schema()

    def _ensure_schema(self) -> None:  # pragma: no cover - exercised at deploy time
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self._table} (
                        id TEXT PRIMARY KEY,
                        member_id TEXT,
                        text TEXT,
                        metadata JSONB,
                        embedding vector({self._vector_size})
                    )
                    """,
                )

    async def search_similar_contexts(
        self,
        *,
        query_text: str,
        member_id: str | None,
        k: int = 5,
    ) -> list[VectorHit]:  # pragma: no cover
        vector = self._embedder(query_text)
        sql = (
            f"SELECT id, member_id, text, metadata, embedding <=> %s::vector AS distance "
            f"FROM {self._table} "
        )
        params: list[Any] = [vector]
        if member_id:
            sql += "WHERE member_id = %s "
            params.append(member_id)
        sql += "ORDER BY distance ASC LIMIT %s"
        params.append(k)
        with self._psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [
            VectorHit(
                id=str(r[0]),
                score=float(r[4]),
                member_id=r[1],
                text=str(r[2] or ""),
                metadata=dict(r[3] or {}),
            )
            for r in rows
        ]

    async def upsert_context(
        self,
        *,
        doc_id: str,
        text: str,
        member_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:  # pragma: no cover
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self._table} (id, member_id, text, metadata, embedding)
                    VALUES (%s, %s, %s, %s::jsonb, %s::vector)
                    ON CONFLICT (id) DO UPDATE SET
                        member_id = EXCLUDED.member_id,
                        text = EXCLUDED.text,
                        metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding
                    """,
                    (
                        doc_id,
                        member_id,
                        text,
                        json.dumps(metadata or {}),
                        self._embedder(text),
                    ),
                )
