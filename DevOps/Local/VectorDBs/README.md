# Local Vector DB stacks

Each subfolder is a self-contained `docker-compose.yml` for one popular
vector backend. Pick the one that matches your `VECTOR_PROVIDER` setting,
or run several at once and use the comma-separated form
(`VECTOR_PROVIDER=qdrant,weaviate,chroma` or `VECTOR_PROVIDER=all`) to
have `MultiVectorClient` fan out upserts and merge searches across them.

| Folder | Backend | Default URL | pip extra |
|---|---|---|---|
| `qdrant/` | Qdrant 1.11 | `http://localhost:6333` | `pip install ".[vector-qdrant]"` |
| `weaviate/` | Weaviate 1.26 + sentence-transformers | `http://localhost:8080` | `pip install ".[vector-weaviate]"` |
| `chroma/` | Chroma 0.5 | `http://localhost:8000` | `pip install ".[vector-chroma]"` |
| `milvus/` | Milvus 2.4 standalone (etcd + minio) | `http://localhost:19530` | `pip install ".[vector-milvus]"` |
| `pgvector/` | Postgres 16 + pgvector | `postgresql://mesa:mesa@localhost:5433/mesa_vectors` | `pip install ".[vector-pgvector]"` |
| (all) | every backend above | n/a | `pip install ".[vector-all]"` |

## Bring one up

```bash
docker compose -f DevOps/Local/VectorDBs/qdrant/docker-compose.yml up -d
```

Then export the matching env vars before starting the API:

```bash
export VECTOR_PROVIDER=qdrant
export VECTOR_URL=http://localhost:6333
export VECTOR_COLLECTION=mesa_member_contexts
uvicorn member_event_stream_agent.main:app --reload
```

## Bring everything up at once

```bash
for d in qdrant weaviate chroma milvus pgvector; do
  docker compose -f "DevOps/Local/VectorDBs/$d/docker-compose.yml" up -d
done
export VECTOR_PROVIDER=all
```

`MultiVectorClient` will then fan out every `upsert_context` call to all
five backends and merge `search_similar_contexts` results across them.
Per-backend failures are logged but never bring the agent down.

## Tear everything down

```bash
for d in qdrant weaviate chroma milvus pgvector; do
  docker compose -f "DevOps/Local/VectorDBs/$d/docker-compose.yml" down -v
done
```

## Notes

- The default ports are picked to not collide with the other infra in
  `DevOps/Local/` (postgres on 5432, kafka on 9092, mongo on 27017).
  pgvector uses 5433 to coexist with the regular postgres stack.
- Embeddings are the **client's** responsibility in this codebase. The
  Qdrant / Milvus / pgvector clients accept an `embedder` callable; the
  Weaviate client offloads embedding to the in-cluster
  `text2vec-transformers` module; the Chroma client falls back to
  Chroma's bundled default embedder if you don't pass one. Wire your
  preferred embedding model (sentence-transformers, Vertex AI, OpenAI)
  at construction time.
- `FakeVectorClient` (the default `VECTOR_PROVIDER=stub`) needs none of
  this — the test suite stays offline and never opens a socket.
