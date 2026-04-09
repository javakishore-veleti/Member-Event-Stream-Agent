# Development Plan — Next 2 Hours

A focused punch list to take `Member-Event-Stream-Agent` from a bare clone to a working vertical slice: a synthetic event flows through a stub consumer, a minimal agent pipeline scores it, MongoDB persists the result, and an MCP tool can read it back.

Total time-box: **120 minutes**. Each task has a hard cap. If a task overruns by more than 50%, stub it and move on — the goal is end-to-end flow first, depth second.

---

## Block 1 — Project skeleton (15 min)

- [ ] **T1.1** (5 min) Create `pyproject.toml` with deps: `fastapi`, `uvicorn[standard]`, `pydantic>=2`, `pymongo`, `aiokafka`, `fastmcp`, `pytest`, `pytest-asyncio`, `httpx`, `python-dotenv`, `structlog`.
- [ ] **T1.2** (3 min) Create package layout under `src/member_event_stream_agent/`:
  ```
  src/member_event_stream_agent/
    __init__.py
    main.py
    api/
    worker/
    agents/
    mcp_server/
    storage/
    config.py
    logging.py
  tests/
  ```
- [ ] **T1.3** (5 min) `pip install -e ".[dev]"` and confirm `python -c "import member_event_stream_agent"` succeeds.
- [ ] **T1.4** (2 min) Add a `.env.example` with `MONGO_URI`, `KAFKA_BROKERS`, `LLM_API_KEY`, `LOG_LEVEL`.

## Block 2 — Domain models + storage (20 min)

- [ ] **T2.1** (8 min) `agents/schemas.py` — Pydantic models: `RawEvent`, `NormalizedEvent`, `Subject`, `RiskScore`, `Recommendation`. Keep fields minimal.
- [ ] **T2.2** (7 min) `storage/mongo.py` — `MongoStore` class wrapping `pymongo.MongoClient`. Methods: `save_event`, `save_score`, `get_subject`, `get_recent_events(subject_id, limit)`. Indexes on `subject_id` and `ts`.
- [ ] **T2.3** (5 min) `tests/test_storage.py` — one smoke test using `mongomock` or a `MagicMock` of the collection. Keep it offline-friendly.

## Block 3 — Worker + synthetic event source (20 min)

- [ ] **T3.1** (10 min) `worker/consumer.py` — async `EventConsumer` with two backends behind one interface:
  - real: `aiokafka.AIOKafkaConsumer`
  - synthetic: an async generator that yields fake events on a timer (for local dev without Kafka).
  Backend selected by `KAFKA_BROKERS` env var (`memory://` → synthetic).
- [ ] **T3.2** (5 min) `worker/normalizer.py` — pure function `normalize(raw: RawEvent) -> NormalizedEvent`. Validate, lowercase keys, strip noise.
- [ ] **T3.3** (5 min) `tests/test_consumer.py` — drive the synthetic backend, assert the normalizer output.

## Block 4 — Minimal agent pipeline (25 min)

- [ ] **T4.1** (5 min) `agents/base.py` — small `Agent` Protocol: `async def run(self, ctx) -> ctx`. Keeps the door open for swapping in real Google ADK later without changing call sites.
- [ ] **T4.2** (5 min) `agents/triage.py` — `TriageAgent`: drops events whose `kind` is in a NOISE set, classifies the rest into a small enum.
- [ ] **T4.3** (5 min) `agents/enrichment.py` — `EnrichmentAgent`: looks up subject and recent events from `MongoStore`, attaches them to ctx.
- [ ] **T4.4** (5 min) `agents/scoring.py` — `ScoringAgent`: rule-based stub for now (count-based heuristic), with a TODO marker for the real LLM call. Returns a `RiskScore`.
- [ ] **T4.5** (5 min) `agents/recommendation.py` — `RecommendationAgent`: maps score thresholds to `dismiss / notify / open_case`.

## Block 5 — Pipeline wiring + persistence (10 min)

- [ ] **T5.1** (6 min) `agents/pipeline.py` — `Pipeline` runs Triage → Enrichment → Scoring → Recommendation; writes the `RiskScore` and `Recommendation` to MongoDB; logs each stage with `structlog`.
- [ ] **T5.2** (4 min) `tests/test_pipeline.py` — feed one synthetic event, assert a `RiskScore` document lands in the (mock) store.

## Block 6 — FastAPI surface (10 min)

- [ ] **T6.1** (4 min) `api/app.py` — `create_app()` factory; `/healthz`, `/version`.
- [ ] **T6.2** (4 min) `api/routes.py` — `GET /subjects/{id}`, `GET /scores/{id}` reading from `MongoStore`.
- [ ] **T6.3** (2 min) `tests/test_api.py` — `httpx.AsyncClient` smoke tests for `/healthz` and one read endpoint.

## Block 7 — FastMCP gateway (15 min)

- [ ] **T7.1** (8 min) `mcp_server/server.py` — `FastMCP` server registering two tools: `subject_lookup(id)` and `recent_events(id, limit)`. Tools delegate to `MongoStore`.
- [ ] **T7.2** (5 min) Token auth stub — read `MCP_TOKEN` from env, reject calls without it. One scope: `read:subjects`.
- [ ] **T7.3** (2 min) `tests/test_mcp.py` — call the tool functions directly (not over the wire) and assert shape.

## Block 8 — Wire-up, run, and CI (5 min)

- [ ] **T8.1** (2 min) `member_event_stream_agent/main.py` — start FastAPI app, mount routes, wire `MongoStore` and `Pipeline` into app state.
- [ ] **T8.2** (2 min) Run locally: `uvicorn member_event_stream_agent.main:app --reload`. Hit `/healthz` and one read endpoint. Run the worker against the synthetic backend (`KAFKA_BROKERS=memory://`).
- [ ] **T8.3** (1 min) `pytest -q` green. Push and confirm the existing GitHub Actions CI workflow runs the suite.

---

## What is intentionally NOT in this 2-hour slice

These belong in the next slice, not this one. Listing them here so they do not creep in:

- Real Google ADK wiring (the Agent Protocol leaves the seam open).
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
5. Calling `subject_lookup` through the MCP server returns a record for that synthetic subject.
6. Two commits are pushed: one for the scaffold/code, one for the README/plan updates.

## Suggested commit checkpoints

- After Block 2: `feat(storage): add Pydantic models and MongoStore`
- After Block 4: `feat(agents): add triage / enrichment / scoring / recommendation stubs`
- After Block 5: `feat(pipeline): wire agent pipeline end to end with persistence`
- After Block 6: `feat(api): add FastAPI app factory and read endpoints`
- After Block 7: `feat(mcp): add FastMCP gateway with subject_lookup and recent_events`
- After Block 8: `chore: wire main entrypoint and synthetic worker run`
