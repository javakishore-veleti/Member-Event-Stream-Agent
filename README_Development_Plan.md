# Development Plan — Next 2 Hours

A focused punch list to take `Member-Event-Stream-Agent` from a Block-1 scaffold to a working vertical slice using the **domain-aware multi-module layout**: a synthetic event flows through `member_events`, `care_decisioning` scores it through an agent pipeline, `member_record` persists the result, `payer_api` reads it back, and `care_team_gateway` exposes it to LLM clients.

The full business framing for the platform lives in [`README_HealthCare.md`](./README_HealthCare.md). This document is the engineering punch list only.

Total time-box: **120 minutes**. Each task has a hard cap. If a task overruns by more than 50%, stub it and move on — the goal is end-to-end flow first, depth second.

## Target package layout

```
src/member_event_stream_agent/
├── member_events/         # Kafka consumer, producer, schemas, normalizer
│   ├── __init__.py
│   ├── consumer.py
│   ├── producer.py
│   ├── schemas.py         # RawEvent, MemberEvent, EventFamily enum
│   └── normalizer.py
├── care_decisioning/      # Multi-agent pipeline lives here
│   ├── __init__.py
│   ├── base.py            # Agent Protocol, PipelineCtx
│   ├── pipeline.py
│   ├── triage.py
│   ├── enrichment.py
│   ├── scoring.py
│   ├── recommendation.py
│   └── prompts/           # templates + guardrails
├── member_record/         # Mongo-backed Member 360
│   ├── __init__.py
│   ├── mongo.py           # MongoStore
│   ├── indexes.py
│   └── schemas.py         # Member, Encounter, ClaimLine, MedicationFill,
│                          # LabResult, RiskScore, Disposition, CaseFile
├── payer_api/             # FastAPI surface
│   ├── __init__.py
│   ├── app.py             # create_app() factory
│   ├── routes.py          # /healthz, /version, /members, /risk-scores
│   └── deps.py            # FastAPI dependency wiring
├── care_team_gateway/     # FastMCP server
│   ├── __init__.py
│   ├── server.py
│   ├── tools.py           # member_lookup, recent_events, panel_overview, ...
│   └── auth.py            # token + scope check + HIPAA audit hook
├── __init__.py
├── config.py
├── logging.py
└── main.py
```

Tests mirror the same tree under `tests/`:

```
tests/
├── member_events/
├── care_decisioning/
├── member_record/
├── payer_api/
└── care_team_gateway/
```

Each block below builds one of those subpackages and lands its tests in the matching `tests/` subfolder.

---

## Block 1 — Project skeleton (DONE)

Block 1 is complete. The domain-aware package tree is in place, the editable install works, and `pytest -q` is green (2/2).

## Block 2 — `member_record/` (20 min)

- [ ] **T2.1** (8 min) `member_record/schemas.py` — Pydantic v2 models for `Member`, `Encounter`, `ClaimLine`, `MedicationFill`, `LabResult`, `RiskScore`, `Disposition`, `CaseFile`. Persistence shapes only — keep them minimal but use real coding fields (`dx_codes: list[str]`, `loinc_code: str`, `ndc: str`).
- [ ] **T2.2** (3 min) `member_record/indexes.py` — declarative list of indexes (`member_id`, `(member_id, ts)` compound, `event_id` unique for idempotency).
- [ ] **T2.3** (8 min) `member_record/mongo.py` — `MongoStore` class wrapping `pymongo.MongoClient`. Methods: `save_event`, `save_score`, `save_disposition`, `get_member`, `get_recent_events(member_id, limit)`, `get_risk_history(member_id, dimension)`. Tenant filter on `payer_org_id` enforced inside the class. Apply indexes on first connect.
- [ ] **T2.4** (3 min) `tests/member_record/test_mongo.py` — use `mongomock` so the suite stays offline-friendly.

## Block 3 — `member_events/` (20 min)

- [ ] **T3.1** (5 min) `member_events/schemas.py` — `RawEvent`, `MemberEvent` Pydantic models, plus an `EventFamily` enum (`ELIGIBILITY`, `ENCOUNTER`, `CLAIM`, `PHARMACY`, `LAB`, `CARE_MGMT`).
- [ ] **T3.2** (4 min) `member_events/normalizer.py` — pure `normalize(raw: RawEvent) -> MemberEvent`. Validate, lowercase keys, strip noise, compute `payload_hash`.
- [ ] **T3.3** (8 min) `member_events/consumer.py` — async `EventConsumer` with two backends behind one interface:
  - real: `aiokafka.AIOKafkaConsumer`
  - synthetic: an async generator that yields fake `ELIGIBILITY` / `ENCOUNTER` / `PHARMACY` events on a timer
  Backend selected by `KAFKA_BROKERS` env var (`memory://` → synthetic).
- [ ] **T3.4** (3 min) `member_events/producer.py` — thin async producer (real Kafka + in-memory variant). Used later for outbound notifications and from tests as a fixture source.

## Block 4 — `care_decisioning/` agents (25 min)

- [ ] **T4.1** (4 min) `care_decisioning/base.py` — `Agent` Protocol: `async def run(self, ctx: PipelineCtx) -> PipelineCtx`. `PipelineCtx` is a dataclass carrying the event, enriched member context, score, citations, and audit trail. Keeps the seam open for swapping in real Google ADK later without changing call sites.
- [ ] **T4.2** (4 min) `care_decisioning/triage.py` — `TriageAgent`: drops events whose `kind` is in a NOISE set, classifies the rest into the family enum, picks the relevant use case (care_gap / readmission / polypharmacy / pa_decision / fwa).
- [ ] **T4.3** (5 min) `care_decisioning/enrichment.py` — `EnrichmentAgent`: pulls member + recent events + active medications from `MongoStore`, attaches to `ctx`.
- [ ] **T4.4** (5 min) `care_decisioning/scoring.py` — `ScoringAgent`: rule-based stub for now (heuristic), with a TODO marker for the real LLM call. Returns a `RiskScore` with cited `event_id`s.
- [ ] **T4.5** (4 min) `care_decisioning/recommendation.py` — `RecommendationAgent`: maps score thresholds to `none / notify_care_manager / open_outreach / queue_pa_review / propose_intervention / escalate_fwa / draft_pa_response`.
- [ ] **T4.6** (3 min) `care_decisioning/prompts/triage.txt` placeholder so the directory shows intent.

## Block 5 — pipeline wire-up (10 min)

- [ ] **T5.1** (6 min) `care_decisioning/pipeline.py` — `Pipeline` constructs the four agents, runs them in order, persists the `RiskScore`, `Disposition`, and immutable `CaseFile` via `MongoStore`, logs every stage with `structlog`.
- [ ] **T5.2** (4 min) `tests/care_decisioning/test_pipeline.py` — feed one synthetic event end-to-end against a `mongomock` store, assert a `RiskScore` and a `CaseFile` document land.

## Block 6 — `payer_api/` FastAPI surface (10 min)

- [ ] **T6.1** (4 min) `payer_api/app.py` — `create_app()` factory; mount `/healthz`, `/version`. `payer_api/deps.py` provides FastAPI `Depends` for `MongoStore` and `Pipeline`.
- [ ] **T6.2** (4 min) `payer_api/routes.py` — `GET /members/{id}`, `GET /members/{id}/risk-history` reading from `MongoStore` via `Depends`.
- [ ] **T6.3** (2 min) `tests/payer_api/test_app.py` — `httpx.AsyncClient` smoke tests for `/healthz` and one read endpoint.

## Block 7 — `care_team_gateway/` FastMCP server (15 min)

- [ ] **T7.1** (4 min) `care_team_gateway/auth.py` — token check (reads `MCP_TOKEN` from env) and scope enforcer (`care_manager`, `um`, `pharmacist`, `quality`, `fwa`). Hooks the HIPAA audit-log call.
- [ ] **T7.2** (5 min) `care_team_gateway/tools.py` — two tool functions to start: `member_lookup(member_id)`, `recent_events(member_id, limit)`. Each delegates to `MongoStore` and applies PHI redaction on the response.
- [ ] **T7.3** (4 min) `care_team_gateway/server.py` — `FastMCP` server registering the two tools through the auth wrapper.
- [ ] **T7.4** (2 min) `tests/care_team_gateway/test_tools.py` — call the tool functions directly (not over the wire) and assert shape + redaction behavior.

## Block 8 — `main.py`, run, and CI (5 min)

- [ ] **T8.1** (2 min) `main.py` — build `MongoStore`, `Pipeline`, `EventConsumer`, MCP server; create the FastAPI app via `create_app()`; mount everything; on startup spawn the consumer task against the synthetic backend.
- [ ] **T8.2** (2 min) Run locally: `uvicorn member_event_stream_agent.main:app --reload` with `KAFKA_BROKERS=memory://`. Hit `/healthz` and one read endpoint.
- [ ] **T8.3** (1 min) `pytest -q` green. Push and confirm GitHub Actions runs the suite.

---

## What is intentionally NOT in this 2-hour slice

These belong in the next slice, not this one. Listing them here so they do not creep in:

- Real Google ADK wiring (the `Agent` Protocol leaves the seam open).
- Real LangChain / LLM provider calls in `ScoringAgent` (currently rule-based).
- Real Kafka cluster (synthetic backend covers it for now).
- Real auth provider (token stub is enough for an end-to-end smoke test).
- Docker / Kubernetes manifests beyond the local infra stacks already in `DevOps/Local/`.
- The full persona-scoped MCP tool catalog (`pa_queue`, `panel_overview`, `cohort_overview`, `related_entities`). Block 7 ships only the first two.
- Real PHI-redaction processor in `logging.py` (placeholder TODO).
- Late-arriving claims rescore worker (real production concern, deferred).

## Definition of done for the 2-hour slice

1. `pytest -q` is green locally and in GitHub Actions.
2. `uvicorn member_event_stream_agent.main:app` starts cleanly.
3. `curl /healthz` returns `{"status":"ok"}`.
4. Running the worker against the synthetic backend produces at least one `RiskScore` and one `CaseFile` document in the (mock) MongoDB collection within 30 seconds.
5. Calling `member_lookup` through the MCP gateway returns a record for that synthetic member with PHI fields redacted by default.
6. Each block lands as its own commit.

## Suggested commit checkpoints

- After Block 2: `feat(member_record): add Pydantic schemas, indexes, and MongoStore`
- After Block 3: `feat(member_events): add Kafka consumer, producer, normalizer, schemas`
- After Block 4: `feat(care_decisioning): add Triage / Enrichment / Scoring / Recommendation agents`
- After Block 5: `feat(care_decisioning): wire agent pipeline end to end with audit trail`
- After Block 6: `feat(payer_api): add FastAPI app factory, deps wiring, and read endpoints`
- After Block 7: `feat(care_team_gateway): add FastMCP server with member_lookup and recent_events`
- After Block 8: `chore: wire main entrypoint and synthetic worker run`
