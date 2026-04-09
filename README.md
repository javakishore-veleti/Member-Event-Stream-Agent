# Member-Event-Stream-Agent

> A FastAPI + Kafka + MongoDB + Google ADK + FastMCP service that scores a stream of member events through a multi-agent pipeline and exposes investigative tools to LLM clients.

## What this project is

`Member-Event-Stream-Agent` is a production-shaped Python backend that turns a high-volume stream of member events into prioritized, explainable risk signals — and then makes those signals (plus the tools to investigate them) available to LLM-powered analyst workflows.

It is built around four ideas:

1. **Event-driven ingestion.** Member events arrive on Kafka topics. A FastAPI worker consumes them with backpressure-aware async handlers and persists raw and normalized records to MongoDB.
2. **Agentic scoring.** Each event (or batched window of events) is run through a Google ADK multi-agent pipeline — Triage → Enrichment → Risk Scoring → Recommendation — so the decision is composable, debuggable, and auditable rather than a single opaque model call.
3. **Tooling for analysts via MCP.** A FastMCP server exposes a small, well-scoped set of investigative tools (subject lookup, recent events, risk history, related-entity expansion) to any MCP-aware LLM client. Tools are auth- and scope-gated so the LLM can only see what the analyst is allowed to see.
4. **Operable from day one.** Structured logging, request/response tracing, health endpoints, and a Pytest + MagicMock test suite are scaffolded in from the first commit, not bolted on later.

The design is intentionally generic. No proprietary code, schemas, customer data, or client identifiers are reproduced. All data is synthetic.

## Architecture at a glance

```
                 ┌──────────────────┐
   member events │   Kafka topic    │
   ───────────▶  │ member.events.*  │
                 └────────┬─────────┘
                          │ async consumer
                          ▼
                 ┌──────────────────┐         ┌──────────────────┐
                 │   FastAPI app    │ ──────▶ │     MongoDB      │
                 │  (worker + API)  │ persist │ events / scores  │
                 └────────┬─────────┘         └──────────────────┘
                          │ invoke
                          ▼
              ┌──────────────────────────┐
              │   Google ADK pipeline    │
              │ Triage → Enrichment →    │
              │ Risk Scoring → Recommend │
              └────────┬─────────────────┘
                       │ writes back
                       ▼
              ┌──────────────────────────┐
              │     FastMCP server       │ ◀── analyst's LLM client
              │  (subject_lookup,        │
              │   recent_events,         │
              │   risk_history,          │
              │   related_entities)      │
              └──────────────────────────┘
```

## Major components

- **`api/`** — FastAPI app: health, admin, and read endpoints (`/subjects/{id}`, `/scores/{id}`, `/healthz`).
- **`worker/`** — async Kafka consumer; pulls events, normalizes, hands off to the agent pipeline, persists results.
- **`agents/`** — Google ADK multi-agent pipeline:
  - `triage_agent` — drops noise, classifies event type.
  - `enrichment_agent` — joins subject context from MongoDB.
  - `scoring_agent` — produces a risk score with rationale.
  - `recommendation_agent` — proposes a next action (notify / open case / dismiss).
- **`mcp_server/`** — FastMCP server exposing investigative tools to LLM clients with token auth and per-tool scope enforcement.
- **`storage/`** — PyMongo client, indexes, and aggregation queries used by the API and the agents.
- **`tests/`** — Pytest suite with MagicMock fakes for Kafka, MongoDB, and the LLM client.

## Capabilities this project demonstrates

| Capability | Where it lives in this repo |
|---|---|
| Python 3.11+ backend services | All of `src/` |
| FastAPI microservice | `api/`, `worker/` |
| MongoDB / PyMongo, complex aggregation | `storage/` |
| Apache Kafka event-driven architecture | `worker/` consumer + producer helpers |
| Google ADK multi-agent system | `agents/` |
| FastMCP server exposing tools to LLMs | `mcp_server/` |
| Prompt engineering, grounding, guardrails | `agents/prompts/` |
| Async / concurrency | FastAPI async handlers + asyncio Kafka consumer |
| Pytest + MagicMock | `tests/` |
| Structured logging / observability | `api/logging.py`, every component |

## Quickstart

> Requires Python 3.11+. Uses standard `pip install -e ".[dev]"` (or `uv` if you prefer).

```bash
# 1. install
pip install -e ".[dev]"

# 2. run the API locally
uvicorn member_event_stream_agent.main:app --reload

# 3. run tests
pytest -q

# 4. health check
curl http://localhost:8000/healthz
```

A `docker-compose.yml` (Kafka + MongoDB) and example `.env` will land alongside the first end-to-end slice.

## Status

This repository is **in active development**.

What is in place today:
- Project scaffold, `pyproject.toml`, package layout.
- FastAPI app with `/healthz`.
- Pytest smoke test.
- GitHub Actions CI workflow.

What is being built next:
- Kafka consumer with a synthetic event generator.
- MongoDB schema + indexes for events and scores.
- ADK Triage and Enrichment agents.
- FastMCP server with the first two investigative tools.

## License

See `LICENSE`.
