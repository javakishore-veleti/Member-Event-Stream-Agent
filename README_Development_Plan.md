# Development Plan — Next 2 Hours

A focused punch list to take `Member-Event-Stream-Agent` from a bare clone to a working vertical slice using a **multi-module package layout**: a synthetic event flows through the events module, the processing module scores it through an agent pipeline, the storage module persists the result, the api module reads it back, and the mcp_gateway module exposes it to LLM clients.

Total time-box: **120 minutes**. Each task has a hard cap. If a task overruns by more than 50%, stub it and move on — the goal is end-to-end flow first, depth second.

## Target package layout

```
src/member_event_stream_agent/
├── events/             # everything about the event stream
│   ├── __init__.py
│   ├── consumer.py     # async consumer (Kafka + synthetic backend)
│   ├── producer.py     # outbound producer (notifications, test fixtures)
│   ├── schemas.py      # RawEvent, NormalizedEvent (Pydantic)
│   └── normalizer.py   # pure normalize() function
├── processing/         # the agent pipeline lives here
│   ├── __init__.py
│   ├── base.py         # Agent Protocol
│   ├── pipeline.py     # orchestrates Triage -> Enrichment -> Scoring -> Recommendation
│   ├── triage.py
│   ├── enrichment.py
│   ├── scoring.py
│   ├── recommendation.py
│   └── prompts/        # templates + guardrails
├── storage/            # persistence
│   ├── __init__.py
│   ├── mongo.py        # MongoStore client + queries
│   ├── indexes.py      # index definitions
│   └── schemas.py      # Subject, RiskScore, Recommendation persistence shapes
├── api/                # FastAPI surface
│   ├── __init__.py
│   ├── app.py          # create_app() factory
│   ├── routes.py       # /healthz, /subjects, /scores
│   └── deps.py         # FastAPI dependency wiring
├── mcp_gateway/        # FastMCP server
│   ├── __init__.py
│   ├── server.py
│   ├── tools.py        # subject_lookup, recent_events, ...
│   └── auth.py         # token + scope check
├── __init__.py
├── config.py           # env-driven settings (pydantic-settings)
├── logging.py          # structlog setup
└── main.py             # entrypoint: mounts api + worker + mcp
```

Mirror layout under `tests/`:

```
tests/
├── events/
├── processing/
├── storage/
├── api/
└── mcp_gateway/
```

Each block below builds one of those subpackages and lands its tests in the matching `tests/` subfolder.

---

## Block 1 — Project skeleton (15 min)

- [ ] **T1.1** (5 min) Create `pyproject.toml` with deps: `fastapi`, `uvicorn[standard]`, `pydantic>=2`, `pydantic-settings`, `pymongo`, `mongomock`, `aiokafka`, `fastmcp`, `structlog`, `python-dotenv`. Dev: `pytest`, `pytest-asyncio`, `httpx`.
- [ ] **T1.2** (5 min) Create the full subpackage tree above (each folder gets an `__init__.py`).
- [ ] **T1.3** (3 min) `pip install -e ".[dev]"` and confirm `python -c "import member_event_stream_agent"` succeeds.
- [ ] **T1.4** (2 min) Add `.env.example` with `MONGO_URI`, `KAFKA_BROKERS`, `LLM_API_KEY`, `LOG_LEVEL`, `MCP_TOKEN`. Add `config.py` reading them via `pydantic-settings`.

## Block 2 — `storage/` module (20 min)

- [ ] **T2.1** (6 min) `storage/schemas.py` — Pydantic models: `Subject`, `RiskScore`, `Recommendation`. Persistence shapes only — keep them minimal.
- [ ] **T2.2** (3 min) `storage/indexes.py` — declarative list of indexes (`subject_id`, `ts`, `(subject_id, ts)` compound).
- [ ] **T2.3** (8 min) `storage/mongo.py` — `MongoStore` class wrapping `pymongo.MongoClient`. Methods: `save_event`, `save_score`, `save_recommendation`, `get_subject`, `get_recent_events(subject_id, limit)`. Apply indexes on first connect.
- [ ] **T2.4** (3 min) `tests/storage/test_mongo.py` — use `mongomock` so the suite stays offline-friendly.

## Block 3 — `events/` module (20 min)

- [ ] **T3.1** (5 min) `events/schemas.py` — `RawEvent`, `NormalizedEvent` Pydantic models.
- [ ] **T3.2** (4 min) `events/normalizer.py` — pure `normalize(raw: RawEvent) -> NormalizedEvent`. Validate, lowercase keys, strip noise.
- [ ] **T3.3** (8 min) `events/consumer.py` — async `EventConsumer` with two backends behind one interface:
  - real: `aiokafka.AIOKafkaConsumer`
  - synthetic: an async generator that yields fake events on a timer
  Backend selected by `KAFKA_BROKERS` env var (`memory://` -> synthetic).
- [ ] **T3.4** (3 min) `events/producer.py` — thin async producer (real Kafka + in-memory variant). Used later for outbound notifications and from tests as a fixture source.

## Block 4 — `processing/` agent pipeline (25 min)

- [ ] **T4.1** (4 min) `processing/base.py` — `Agent` Protocol: `async def run(self, ctx: PipelineCtx) -> PipelineCtx`. `PipelineCtx` is a small dataclass carrying the event, enrichment, score, and audit trail. Keeps the seam open for swapping in real Google ADK later without changing call sites.
- [ ] **T4.2** (4 min) `processing/triage.py` — `TriageAgent`: drops events whose `kind` is in a NOISE set, classifies the rest into a small enum.
- [ ] **T4.3** (5 min) `processing/enrichment.py` — `EnrichmentAgent`: pulls subject + recent events from `MongoStore`, attaches them to `ctx`.
- [ ] **T4.4** (5 min) `processing/scoring.py` — `ScoringAgent`: rule-based stub for now (count-based heuristic). TODO marker for the real LLM call. Returns a `RiskScore`.
- [ ] **T4.5** (4 min) `processing/recommendation.py` — `RecommendationAgent`: maps score thresholds to `dismiss / notify / open_case`.
- [ ] **T4.6** (3 min) `processing/prompts/` — empty package with one `triage.txt` placeholder so the directory shows intent.

## Block 5 — `processing/pipeline.py` wire-up (10 min)

- [ ] **T5.1** (6 min) `processing/pipeline.py` — `Pipeline` constructs the four agents, runs them in order, persists the `RiskScore` and `Recommendation` via `MongoStore`, logs every stage with `structlog`.
- [ ] **T5.2** (4 min) `tests/processing/test_pipeline.py` — feed one synthetic event end-to-end against a `mongomock` store, assert a `RiskScore` document lands.

## Block 6 — `api/` FastAPI surface (10 min)

- [ ] **T6.1** (4 min) `api/app.py` — `create_app()` factory; mount `/healthz`, `/version`. `api/deps.py` provides FastAPI `Depends` for `MongoStore` and `Pipeline`.
- [ ] **T6.2** (4 min) `api/routes.py` — `GET /subjects/{id}`, `GET /scores/{id}` reading from `MongoStore` via `Depends`.
- [ ] **T6.3** (2 min) `tests/api/test_app.py` — `httpx.AsyncClient` smoke tests for `/healthz` and one read endpoint.

## Block 7 — `mcp_gateway/` FastMCP server (15 min)

- [ ] **T7.1** (4 min) `mcp_gateway/auth.py` — token check (reads `MCP_TOKEN` from env) and a tiny scope enforcer (`read:subjects`).
- [ ] **T7.2** (5 min) `mcp_gateway/tools.py` — two tool functions: `subject_lookup(id)`, `recent_events(id, limit)`. Each delegates to `MongoStore`.
- [ ] **T7.3** (4 min) `mcp_gateway/server.py` — `FastMCP` server registering the two tools through the auth wrapper.
- [ ] **T7.4** (2 min) `tests/mcp_gateway/test_tools.py` — call the tool functions directly (not over the wire) and assert shape.

## Block 8 — `main.py`, run, and CI (5 min)

- [ ] **T8.1** (2 min) `main.py` — build `MongoStore`, `Pipeline`, `EventConsumer`, `MCP server`; create the FastAPI app via `create_app()`; mount everything; on startup spawn the consumer task against the synthetic backend.
- [ ] **T8.2** (2 min) Run locally: `uvicorn member_event_stream_agent.main:app --reload` with `KAFKA_BROKERS=memory://`. Hit `/healthz` and one read endpoint.
- [ ] **T8.3** (1 min) `pytest -q` green. Push and confirm GitHub Actions runs the suite.

---

## What is intentionally NOT in this 2-hour slice

These belong in the next slice, not this one. Listing them here so they do not creep in:

- Real Google ADK wiring (the `Agent` Protocol leaves the seam open).
- Real LangChain / LLM provider calls in `ScoringAgent` (currently rule-based).
- Real Kafka cluster (synthetic backend covers it for now).
- Real auth provider (token stub is enough for an end-to-end smoke test).
- Docker / Kubernetes manifests.
- The other three tools on the MCP gateway (`risk_history`, `related_entities`).
- Prompt grounding, evals, guardrails — placeholder TODOs are fine.

## Definition of done for the 2-hour slice

1. `pytest -q` is green locally and in GitHub Actions.
2. `uvicorn member_event_stream_agent.main:app` starts cleanly.
3. `curl /healthz` returns `{"status":"ok"}`.
4. Running the worker against the synthetic backend produces at least one `RiskScore` document in the (mock) MongoDB collection within 30 seconds.
5. Calling `subject_lookup` through the MCP gateway returns a record for that synthetic subject.
6. Each block lands as its own commit.

## Suggested commit checkpoints

- After Block 1: `chore: scaffold multi-module package layout`
- After Block 2: `feat(storage): add Pydantic schemas, indexes, and MongoStore`
- After Block 3: `feat(events): add consumer, producer, normalizer, and event schemas`
- After Block 4: `feat(processing): add triage, enrichment, scoring, recommendation agents`
- After Block 5: `feat(processing): wire agent pipeline end to end with persistence`
- After Block 6: `feat(api): add FastAPI app factory, deps wiring, and read endpoints`
- After Block 7: `feat(mcp_gateway): add FastMCP server with subject_lookup and recent_events`
- After Block 8: `chore: wire main entrypoint and synthetic worker run`
