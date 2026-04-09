"""Vector retrieval seam for care_decisioning.

Mirrors the LlmClient seam in care_decisioning/adk/: a thin Protocol with
typed responses, a FakeVectorClient for offline tests, and one concrete
client per popular vector backend (Qdrant / Weaviate / Chroma / Milvus /
pgvector). Production code talks to the Protocol; deployments swap
backends via VECTOR_PROVIDER without touching agent code.
"""
