# Member-Event-Stream-Agent

> A real-time, event-driven **member event platform** for a health insurance payer (MCO / PBM / managed care org). FastAPI + Kafka + MongoDB + Google ADK multi-agent pipeline + FastMCP gateway.

## What this project is

`Member-Event-Stream-Agent` ingests every signal a payer generates about a health plan member — eligibility, encounters, claims, pharmacy, labs, care-management interactions — runs each event through a multi-agent decisioning pipeline, persists every disposition with HIPAA-grade audit, and exposes scoped investigative tools to clinical and operational staff (care managers, utilization managers, clinical pharmacists, quality / HEDIS analysts, FWA investigators) through an MCP gateway used by their LLM clients.

The full domain model, named use cases, personas, and production-grade NFR surface are documented in [`README_HealthCare.md`](./README_HealthCare.md). This README is the technical / operational quick reference.

## Architecture at a glance

```
                 ┌──────────────────┐
   member events │   Kafka topic    │
   ───────────▶  │ member.events.*  │
                 └────────┬─────────┘
                          │ async consumer
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
              └────────┬─────────────────┘
                       │ writes Disposition + CaseFile
                       ▼
              ┌──────────────────────────┐
              │   care_team_gateway      │ ◀── care manager / UM / pharmacist /
              │   (FastMCP server)       │     HEDIS analyst / FWA investigator
              │ panel_overview,          │     via their MCP-aware LLM client
              │ pa_queue, member_lookup, │
              │ risk_history, ...        │
              └──────────────────────────┘
```

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
| [`README_HealthCare.md`](./README_HealthCare.md) | Domain model, named use cases, personas, MCP tool catalog, NFR surface. **Single source of truth for the business.** |
| [`README_Development_Plan.md`](./README_Development_Plan.md) | Two-hour vertical-slice dev plan, block by block, mapped to packages. |
| [`Docs/Design/architecture.drawio`](./Docs/Design/architecture.drawio) | 5-tab draw.io file: System Overview, Agent Pipeline, MCP Gateway, Event Lifecycle, Deployment View. |

## Status

This repository is **in active development**.

What is in place today:
- Domain-aware multi-module package layout (`member_events`, `care_decisioning`, `member_record`, `payer_api`, `care_team_gateway`).
- `pyproject.toml`, hatchling build, editable install via `npm run setup:local:all`.
- FastAPI app factory with `/healthz` and `/version`.
- Pytest smoke tests (currently 2/2 green).
- GitHub Actions CI workflow.
- Local infra stacks (postgres, mongodb, kafka) on a dedicated docker network with control scripts.
- 5-page draw.io architecture diagrams.

What is being built next (per the dev plan):
- `member_record/` storage schemas and `MongoStore`.
- `member_events/` async consumer (Kafka + synthetic backend) and normalizer.
- `care_decisioning/` Triage / Enrichment / Scoring / Recommendation agents and pipeline wiring.
- `payer_api/` read endpoints and dependency wiring.
- `care_team_gateway/` FastMCP server with the first persona-scoped tools.

## License

See `LICENSE`.
