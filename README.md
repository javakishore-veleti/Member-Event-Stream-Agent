# Member-Event-Stream-Agent

> A real-time, event-driven **member event platform** for a health insurance payer (MCO / PBM / managed care org). FastAPI + Kafka + MongoDB + Google ADK multi-agent decisioning + FastMCP analyst gateway.

## TL;DR

`Member-Event-Stream-Agent` is the kind of internal system a payer's data engineering team owns. It ingests every signal a payer generates about a health plan member — eligibility, encounters, claims, pharmacy, labs, care management — runs each event through a multi-agent decisioning pipeline, persists every disposition with HIPAA-grade audit, and exposes scoped investigative tools to clinical and operational staff (care managers, utilization managers, clinical pharmacists, quality / HEDIS analysts, FWA investigators) through an MCP gateway used by their LLM clients.

The full domain model and the rationale for choosing it live in [`README_HealthCare.md`](./README_HealthCare.md). This README is the technical landing page.

## What it does — 5 named, money-on-the-line use cases

Each use case ties to a real measurement framework or operational workflow. The agent pipeline (Triage → Enrichment → Scoring → Recommendation) produces a `Disposition` for every one of them, with full citations and an immutable `CaseFile` per decision.

| # | Use case | Trigger | Pipeline output | Real-world consequence |
|---|---|---|---|---|
| 1 | **HEDIS / Stars care-gap closure** | `eligibility` boundary or new `encounter` | `open_outreach` with the open measure (e.g. `BCS-E`, `CDC-HbA1c`) and cited evidence | CMS Star Ratings drive billions in MA plan bonus payments |
| 2 | **30-day readmission risk** | `inpatient_discharge` arrives via ADT | `notify_care_manager` with cited risk drivers (prior admits, polypharmacy, follow-up gap) | CMS HRRP penalties; one prevented admit saves $15–25k |
| 3 | **Polypharmacy & drug-drug interaction** | `rx_filled` against active medication list | `notify_care_manager` or `propose_intervention` with the cited interaction | Part D adherence measures are 3x-weighted in Star Ratings |
| 4 | **Prior-authorization triage** | `prior_auth_requested` | `queue_pa_review` or `draft_pa_response` with cited guideline | CMS 2024 PA final rule: 24h urgent / 7d standard turnaround |
| 5 | **FWA (fraud, waste, abuse) pattern detection** | claim + pharmacy + provider event clusters | `escalate_fwa` with the suspicious cluster + investigation steps | CMS-required SIU function; multi-billion-dollar problem industry-wide |

## Who uses it — personas and the MCP tool surface

The `care_team_gateway` (FastMCP server) exposes scoped, persona-aware tools to MCP-aware LLM clients. Auth and per-tool scope enforcement is real business logic — not theatre — and every call writes a HIPAA audit-log entry.

| Persona | What they ask | Tools they call (scoped) |
|---|---|---|
| **Care Manager** | "Which of my panel have an open care gap and a recent ED visit?" | `member_lookup`, `recent_events`, `risk_history(care_gap)`, `panel_overview`, `case_lookup` |
| **Utilization Manager** | "Show today's PA queue with the agent-drafted response and cited guideline." | `pa_queue`, `case_lookup`, `risk_history(pa_decision)` |
| **Clinical Pharmacist** | "Which members on my panel are flagged for polypharmacy this week?" | `risk_history(polypharmacy)`, `recent_events(family=PHARMACY)` |
| **Quality / HEDIS Analyst** | "Diabetic A1c gap closure rate by PCP cohort this quarter." | `cohort_overview`, `risk_history(care_gap, measure_id=...)` |
| **FWA Investigator** | "Pull the related provider/member graph for this suspected upcoding cluster." | `related_entities`, `case_lookup`, `risk_history(fwa)` |

Tenant isolation by `payer_org_id` is enforced at the gateway, not just at storage. PHI fields tagged `phi=true` in the schema are stripped or hashed in MCP responses unless the caller scope explicitly permits them.

## Why this is production-grade (and not academic)

- **Money on the line.** CMS Star Ratings tie billions in payer revenue to quality measure performance. Wrong PA dispositions trigger CMS turnaround-time penalties.
- **Regulatory pressure.** HIPAA, NCQA, CMS Stars, HEDIS measure specs, the CMS 2024 Prior Authorization final rule, MCO contractual SLAs — they shape the audit and observability surface, not just the README.
- **Hard engineering problems.** Claims are notoriously replayed and re-adjudicated, so idempotency is mandatory. PHI must never appear in logs. Member IDs are hashable. Multi-tenancy by payer org. Schema evolution because FHIR R4 keeps growing. Late-arriving claims (30–90 days) require historical re-scoring without re-notifying analysts.
- **Defensible agent pipeline.** Care gap closure, readmission risk, polypharmacy / DDI, PA triage, FWA pattern detection — real engineering line items in any payer.

## Production-grade by design

| Concern | How the platform handles it |
|---|---|
| **Idempotency** | `event_id + source_system` is the dedup key; Kafka replays are safe (claims ARE replayed in adjudication). |
| **Replay & backfill** | Worker mode that re-scores a date range without writing notifications. Required for HEDIS measure-spec annual updates. |
| **Late-arriving data** | Historical rescore on late claims; emits "score-changed" events without re-notifying analysts who already worked the case. |
| **Partitioning** | Kafka topic partitioned by `member_id` so all events for a member land on the same consumer (ordering required for episode grouping). |
| **Schema evolution** | Pydantic v2 models versioned; FHIR R4-aligned shapes; unknown fields preserved in `attributes` so producers can roll forward. |
| **PHI hygiene** | structlog processors strip / hash any field tagged `phi=true` before serialization. Logs never carry cleartext member identifiers. |
| **HIPAA audit** | Every `Disposition` writes an immutable `CaseFile` with inputs hash, full agent trace, model version, reviewer, and PHI access log. |
| **Multi-tenant** | Every collection partitioned by `payer_org_id`; the MCP scope check enforces tenant isolation. |
| **DLQ** | Failed scoring decisions write to `dispositions.deadletter` with the event payload and failure reason for analyst replay. |
| **Configurable rules** | HEDIS measure definitions, formulary, PA criteria live in MongoDB and are hot-reloadable per tenant. No redeploy to tune thresholds. |
| **Observability** | Per-stage structured log, per-tool MCP audit log, latency histograms, Kafka lag metrics, prior-auth turnaround SLA tracking. |

## Architecture at a glance

```
                 ┌──────────────────┐
   member events │   Kafka topic    │
   ───────────▶  │ member.events.*  │  partitioned by member_id
                 └────────┬─────────┘
                          │ async consumer (idempotent on event_id)
                          ▼
                 ┌──────────────────┐         ┌──────────────────┐
                 │  payer_api +     │ ──────▶ │   member_record  │
                 │  worker process  │ persist │  (Mongo Member   │
                 └────────┬─────────┘         │    360 store)    │
                          │ invoke            └──────────────────┘
                          ▼
              ┌──────────────────────────┐
              │   care_decisioning       │
              │ Triage → Enrichment →    │
              │ Scoring → Recommendation │
              │ writes immutable CaseFile│
              └────────┬─────────────────┘
                       │ Disposition + CaseFile
                       ▼
              ┌──────────────────────────┐
              │   care_team_gateway      │ ◀── care manager / UM / pharmacist /
              │   (FastMCP server)       │     HEDIS analyst / FWA investigator
              │ panel_overview, pa_queue,│     via their MCP-aware LLM client
              │ member_lookup,           │
              │ risk_history, ...        │
              └──────────────────────────┘
```

The full 5-tab draw.io is in [`Docs/Design/architecture.drawio`](./Docs/Design/architecture.drawio): System Overview, care_decisioning Pipeline, care_team_gateway (MCP), Event Lifecycle, Deployment View.

## Domain-aware package layout

| Package | Role |
|---|---|
| `member_events/` | Kafka consumer / producer, event schemas (`ELIGIBILITY`, `ENCOUNTER`, `CLAIM`, `PHARMACY`, `LAB`, `CARE_MGMT`), source-system normalizer. |
| `care_decisioning/` | Multi-agent pipeline (`Triage → Enrichment → Scoring → Recommendation`) plus prompt templates and guardrails. |
| `member_record/` | MongoDB-backed longitudinal Member 360: `Member`, `Encounter`, `ClaimLine`, `MedicationFill`, `LabResult`, `RiskScore`, `Disposition`, `CaseFile`. Indexes, aggregation queries, PHI-safe accessors. |
| `payer_api/` | FastAPI surface for clinical and operational staff: member lookup, panel views, cohort queries, case files, `/healthz`, `/version`. |
| `care_team_gateway/` | FastMCP server exposing scoped, persona-aware tools to LLM clients. Token auth, per-tool scope enforcement, HIPAA audit log on every call. |
| `config.py` | `pydantic-settings`-driven configuration. |
| `logging.py` | `structlog` setup with PHI-aware processors. |
| `main.py` | Process entrypoint wiring the FastAPI app, the worker, and the MCP gateway. |

Tests live under `tests/<package_name>/` and mirror the same tree.

## Capabilities this project demonstrates

| Capability | Where it lives in this repo |
|---|---|
| Python 3.11+ backend services | All of `src/` |
| FastAPI microservice | `payer_api/` |
| MongoDB / PyMongo, complex aggregation | `member_record/` |
| Apache Kafka event-driven architecture | `member_events/` |
| Google ADK multi-agent system | `care_decisioning/` |
| FastMCP server exposing tools to LLMs | `care_team_gateway/` |
| Prompt engineering, grounding, guardrails | `care_decisioning/prompts/` |
| Async / concurrency | FastAPI async handlers + asyncio Kafka consumer |
| Pytest + MagicMock | `tests/` |
| HIPAA-aware structured logging / audit | `logging.py`, `care_team_gateway/`, `member_record/` |

## Quickstart

> Requires Python 3.11+ and Docker (for the local infra stacks). The repo provides an `npm`-style task runner over the bash scripts under `DevOps/Local/` so a fresh clone goes from zero to running with one command.

```bash
# 1. set up the project venv at $HOME/runtime_data/python_venvs/Member-Event-Stream-Agent
#    and editable-install the repo with [dev] extras
npm run setup:local:all

# 2. start local infra (postgres, mongodb, kafka) on the dedicated mesa-local-net network
npm run local:docker:start

# 3. check infra health
npm run local:docker:status

# 4. run the API locally
source $HOME/runtime_data/python_venvs/Member-Event-Stream-Agent/bin/activate
uvicorn member_event_stream_agent.main:app --reload

# 5. run tests
pytest -q

# 6. health check
curl http://localhost:8000/healthz

# 7. tear down (destructive: deletes volumes AND removes the docker network)
npm run local:docker:stop
```

See `DevOps/Local/` for the per-service `docker-compose.yml` files and the underlying control scripts.

## Documentation

| File | What it covers |
|---|---|
| [`README_HealthCare.md`](./README_HealthCare.md) | **Single source of truth for the business.** Domain model, named use cases, personas, MCP tool catalog, NFR surface, package mapping, honest interview line. |
| [`README_Development_Plan.md`](./README_Development_Plan.md) | Two-hour vertical-slice dev plan, block by block, mapped to packages. |
| [`Docs/Design/architecture.drawio`](./Docs/Design/architecture.drawio) | 5-tab draw.io file: System Overview, care_decisioning Pipeline, care_team_gateway, Event Lifecycle, Deployment View. |

## Status

This repository is **in active development**.

What is in place today:
- Domain-aware multi-module package layout (`member_events`, `care_decisioning`, `member_record`, `payer_api`, `care_team_gateway`).
- `pyproject.toml`, hatchling build, editable install via `npm run setup:local:all`.
- FastAPI app factory with `/healthz` and `/version`.
- Pytest smoke tests (currently 2/2 green).
- GitHub Actions CI workflow.
- Local infra stacks (postgres, mongodb, kafka) on a dedicated docker network with control scripts.
- 5-tab draw.io architecture diagrams reflecting the healthcare domain.

What is being built next (per the dev plan):
- `member_record/` storage schemas and `MongoStore`.
- `member_events/` async consumer (Kafka + synthetic backend) and normalizer.
- `care_decisioning/` Triage / Enrichment / Scoring / Recommendation agents and pipeline wiring with the 5 named use cases as test fixtures.
- `payer_api/` read endpoints and dependency wiring.
- `care_team_gateway/` FastMCP server with the first persona-scoped tools and HIPAA audit hook.

## License

See `LICENSE`.
