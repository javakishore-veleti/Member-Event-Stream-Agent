"""member_event_stream_agent — multi-module package root.

Subpackages:
    events       — Kafka consumer/producer, raw + normalized event schemas, normalizer.
    processing   — Agent pipeline (Triage → Enrichment → Scoring → Recommendation).
    storage      — MongoDB client, indexes, persistence schemas.
    api          — FastAPI surface (app factory, routes, deps).
    mcp_gateway  — FastMCP server exposing investigative tools to LLM clients.
"""

__version__ = "0.1.0"
