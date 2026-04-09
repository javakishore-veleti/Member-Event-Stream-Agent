# README — Health Plan Member Event Platform

> The business and product framing for `Member-Event-Stream-Agent`. This document is the single source of truth for the domain. Code, tests, and architecture diagrams must align with what is described here.

## TL;DR

A real-time, event-driven **member event platform** from the perspective of a health insurance payer (MCO / PBM / managed care org). It ingests every signal a payer generates about a member — eligibility, encounters, claims, pharmacy, labs, care management — and runs each event through a multi-agent decisioning pipeline that powers care-gap closure, readmission risk, polypharmacy and DDI checks, prior-authorization triage, and FWA pattern detection. Every disposition is persisted with HIPAA-grade audit, and clinical and operational staff can investigate via an MCP-secured tool gateway used by their LLM clients.

The word "member" here is the actual industry term — health plan enrollees are called "members" in payer-speak.

## Why this domain (and why not the alternatives)

| Alternative | Why it was rejected |
|---|---|
| Workforce productivity insights | Too generic; reads as a hack-day demo, no money-on-the-line stakes, no regulatory surface. |
| Banking fraud / credit risk | Commoditized in ML tutorials and Kaggle. Reads as academic on a senior portfolio. |
| Clinical-trial document RAG | Already covered by a sibling repo (`enterprise-document-rag`). |
| In-home care visit document intelligence | Already covered by a sibling repo (`field-service-document-intelligence`). |

Health-plan member events fill the one gap left in the portfolio: a healthcare event-stream platform with payer-side regulatory depth, distinct in both data shape and stakeholder from the two document-centric healthcare repos.

## Why this is production-grade (not academic)

- **Money on the line.** CMS Star Ratings tie billions in payer revenue to quality measure performance. Missed HEDIS care gaps cost real bonus dollars. Wrong prior-authorization dispositions trigger CMS turnaround-time penalties under the 2024 Prior Authorization final rule.
- **Regulatory pressure.** HIPAA, NCQA, CMS Stars, HEDIS measure specs, MCO contractual SLAs. None of these are decorative — they shape the audit and observability surface of the code.
- **Real engineering hard problems.** Claims are notoriously replayed and re-adjudicated, so idempotency is mandatory. PHI must never appear in logs. Member IDs must be hashable. Multi-tenancy by payer org. Schema evolution because FHIR R4 resources keep growing. Late-arriving claims (30–90 days) require historical re-scoring without re-notifying analysts.
- **The agent pipeline has a defensible job.** Care gap closure, readmission risk, polypharmacy / DDI, PA triage, and FWA pattern detection are real engineering line items in any payer org.

## Domain entities

| Entity | Purpose |
|---|---|
| `Member` | Health plan enrollee. `member_id`, `plan_id`, `line_of_business` (`commercial / medicare / medicaid / dsnp`), `eligibility_start`, `eligibility_end`, `dob_year` (year only), `zip3`, `hcc_risk_score`, `pcp_provider_id`. No name, no full DOB, no SSN — demo-safe. |
| `Provider` | `provider_id`, `npi_hash`, `specialty`, `network_status`. |
| `Encounter` | `encounter_id`, `member_id`, `provider_id`, `encounter_type` (`office / ed / inpatient / telehealth`), `service_date`, `primary_dx_codes`, `place_of_service`. |
| `ClaimLine` | `claim_id`, `line_id`, `member_id`, `provider_id`, `service_date`, `dx_codes`, `procedure_code`, `billed_amount`, `allowed_amount`, `paid_amount`, `adjudication_status`. |
| `MedicationFill` | `fill_id`, `member_id`, `prescriber_id`, `ndc`, `days_supply`, `fill_date`, `refills_remaining`. |
| `LabResult` | `result_id`, `member_id`, `loinc_code`, `value`, `unit`, `observed_at`, `abnormal_flag`. |
| `MemberEvent` | The unified envelope every source produces and Kafka carries. `event_id`, `member_id`, `family`, `kind`, `ts`, `source_system`, `payload_hash`, `attributes`. |
| `RiskScore` | `member_id`, `dimension` (`readmission / care_gap / adherence / polypharmacy / fwa / pa_decision`), `score`, `confidence`, `rationale`, `citations[event_id]`, `model_version`, `produced_at`, `valid_until`. |
| `Disposition` | Action chosen by the pipeline: `none / notify_care_manager / open_outreach / queue_pa_review / propose_intervention / escalate_fwa / draft_pa_response`. |
| `CaseFile` | Immutable audit record per disposition: inputs hash, full agent trace per stage, model version, human reviewer, PHI access log, closed_at. |

## Event families

| Family | Example kinds | Source system |
|---|---|---|
| `ELIGIBILITY` | `member_enrolled`, `member_terminated`, `plan_changed`, `benefits_updated` | enrollment / membership platform |
| `ENCOUNTER` | `office_visit`, `ed_visit`, `inpatient_admit`, `inpatient_discharge`, `telehealth_visit` | ADT feed (real-time) |
| `CLAIM` | `claim_received`, `claim_adjudicated`, `claim_denied`, `claim_reversed` | claims platform (often delayed 30–90d) |
| `PHARMACY` | `rx_filled`, `rx_refill_requested`, `rx_denied`, `prior_auth_requested`, `prior_auth_decision` | PBM feed |
| `LAB` | `lab_ordered`, `lab_resulted`, `lab_abnormal_flagged` | lab vendor HL7 / FHIR feed |
| `CARE_MGMT` | `care_plan_created`, `intervention_scheduled`, `intervention_completed`, `member_outreach_attempted` | care management platform |

All events are synthetic. No real PHI is shipped or stored.

## Named use cases (what the agent pipeline actually decides)

Each use case ties to a real measurement framework or operational workflow.

### 1. HEDIS / Stars care-gap closure

When an `eligibility` boundary or `encounter` event arrives, evaluate which guideline-recommended actions are open for that member (e.g., `BCS-E` breast cancer screening, `CDC-HbA1c` diabetes A1c testing, `COL-E` colorectal screening). Triage filters members not eligible for the measure. Enrichment loads claim / lab / pharmacy history showing whether the gap is already closed. Scoring agent reasons over the evidence and produces a `RiskScore` with `measure_id` cited. Recommendation: `open_outreach` with the specific gap and the cited evidence.

> *Real consequence:* HEDIS scores drive Star Ratings, which drive billions in CMS bonus payments to Medicare Advantage plans.

### 2. 30-day readmission risk

`inpatient_discharge` event arrives via ADT. Pipeline pulls 90 days of prior events, scores readmission likelihood, and routes high-risk members to a care manager with the rationale and the specific risk drivers cited (e.g., "prior CHF admit 47 days ago, no PCP follow-up scheduled, polypharmacy with diuretic gap"). Recommendation: `notify_care_manager`.

> *Real consequence:* CMS HRRP penalties make readmission prevention a real engineering line item; one prevented admit saves $15–25k.

### 3. Polypharmacy and drug-drug interaction (DDI)

`rx_filled` event arrives. Pipeline retrieves the active medication list, checks against a DDI rules table plus a synthetic clinical-knowledge corpus, and flags duplicate-therapy or contraindicated combinations. Recommendation: `notify_care_manager` or `propose_intervention` with the cited interaction.

> *Real consequence:* The three Part D adherence measures are Star Ratings 3x-weighted; adherence drift directly affects plan revenue.

### 4. Prior-authorization triage (CMS turnaround-time compliance)

`prior_auth_requested` event arrives. Pipeline retrieves the relevant clinical guideline, the member's history, and the requesting provider's network status, then proposes `Approve / Pend for Review / Deny` with a draft response and citations. The CMS 2024 Prior Authorization final rule (24-hour urgent / 7-day standard turnaround) is the SLA the architecture is built around. Recommendation: `queue_pa_review` or `draft_pa_response`.

> *Real consequence:* CMS turnaround-time penalties; member abrasion and provider relations.

### 5. FWA (fraud, waste, and abuse) pattern detection

Pattern detection across `claim` + `pharmacy` + `provider` events: upcoding patterns, doctor shopping, phantom services. Pipeline ends in `escalate_fwa` with the cluster of events, the suspicious pattern label, and the suggested investigation steps for the Special Investigation Unit.

> *Real consequence:* FWA is a multi-billion-dollar problem for payers; CMS requires payers to operate active SIU programs.

## Personas and the MCP tool surface

The MCP gateway (`care_team_gateway/`) exposes scoped, persona-aware tools:

| Persona | Daily question | Tools they use |
|---|---|---|
| **Care Manager** | "Which of my panel have an open care gap and a recent ED visit?" | `member_lookup`, `recent_events`, `risk_history(dimension=care_gap)`, `panel_overview`, `case_lookup` |
| **Utilization Manager** | "Show today's PA queue with the agent-drafted response and cited guideline." | `pa_queue`, `case_lookup`, `risk_history(dimension=pa_decision)` |
| **Clinical Pharmacist** | "Which members on my panel are flagged for polypharmacy this week?" | `risk_history(dimension=polypharmacy)`, `recent_events(family=PHARMACY)` |
| **Quality / HEDIS Analyst** | "Gap closure rate for diabetic A1c by PCP cohort this quarter." | `cohort_overview`, `risk_history(dimension=care_gap, measure_id=...)` |
| **FWA Investigator** | "Pull the related provider/member graph for this suspected upcoding cluster." | `related_entities`, `case_lookup`, `risk_history(dimension=fwa)` |

Auth and scope enforcement is real business logic, not theatre:

- A care manager can only call tools for members assigned to their panel.
- A pharmacist scope cannot return FWA-dimension scores.
- A FWA investigator can pull cross-member graphs but every call is audit-logged.
- Every MCP response is **PHI-redaction-aware** — fields tagged `phi=true` in the schema are hashed or stripped before returning to the LLM client unless the caller scope explicitly permits them.
- Tenant isolation by `payer_org_id` is enforced at the gateway, not just at the storage layer.

## Production-grade NFR surface

| Concern | How the platform handles it |
|---|---|
| **Idempotency** | `event_id` + `source_system` is the dedup key; replays from Kafka are safe (claims ARE replayed in adjudication). |
| **Replay & backfill** | Worker mode that re-scores a date range without writing notifications. Required for HEDIS measure-spec annual updates. |
| **Late-arriving data** | Claims arrive 30–90 days late. The platform rescores historical windows when late data lands and emits "score-changed" events without re-notifying analysts who already worked the case. |
| **Partitioning** | Kafka topic partitioned by `member_id` so all events for a member land on the same consumer (ordering required for episode grouping). |
| **Schema evolution** | Pydantic v2 models versioned; aligned with FHIR R4 resource shapes (`Encounter`, `Claim`, `MedicationRequest`, `Observation`). Unknown fields preserved in `attributes`. |
| **PHI hygiene** | structlog processors strip / hash any field tagged `phi=true` before serialization. Logs never carry cleartext member identifiers. |
| **Audit trail** | Every `Disposition` writes an immutable `CaseFile` with the inputs hash, full agent trace, model version, human reviewer, and PHI access log. |
| **Multi-tenant** | Every collection partitioned by `payer_org_id`. The MCP scope check enforces tenant isolation. |
| **DLQ** | Failed scoring decisions write to `dispositions.deadletter` with the event payload and failure reason for analyst replay. |
| **Configurable rules** | HEDIS measure definitions, formulary, PA criteria live in MongoDB and are hot-reloadable per tenant. No redeploy to tune thresholds. |
| **Observability** | Per-stage structured log, per-tool MCP audit log, latency histograms, Kafka lag metrics, prior-auth turnaround SLA tracking. |

## Domain-aware package layout

The Python package layout matches the domain, not generic technical buckets:

| Package | Role |
|---|---|
| `member_events/` | Kafka consumer / producer, raw + normalized event schemas, source-system normalizer. |
| `care_decisioning/` | Multi-agent pipeline (Triage → Enrichment → Scoring → Recommendation) and prompt templates. |
| `member_record/` | MongoDB-backed longitudinal Member 360: persistence schemas, indexes, aggregation queries. |
| `payer_api/` | FastAPI surface for clinical and operational staff (member lookup, panel views, cohort queries, case files). |
| `care_team_gateway/` | FastMCP server exposing scoped, persona-aware tools to LLM clients. |
| `config.py` | pydantic-settings for env-driven config. |
| `logging.py` | structlog setup with PHI-aware processors. |
| `main.py` | Process entrypoint that wires the FastAPI app, the consumer, and the MCP gateway. |

Tests live under `tests/<package_name>/` and mirror the same tree.

## Honest interview line

> *"This is a portfolio reference implementation of a real-time member event platform from a health-insurance payer's perspective. It ingests every event a payer generates about a member — eligibility, encounters, claims, pharmacy, labs, care management — and runs them through a multi-agent decisioning pipeline that handles HEDIS care gap closure, 30-day readmission risk, polypharmacy and DDI, prior-authorization triage, and FWA pattern detection. Every decision is persisted with HIPAA-grade audit, and clinical and operational analysts can investigate via an MCP-secured tool gateway from their LLM clients. The architectural patterns — idempotent event ingestion, multi-stage agent pipelines, scoped tool exposure to analysts, and immutable audit dispositions — are patterns I have shipped in distributed systems before; this repo brings them together against a healthcare event domain because the regulatory and operational depth make it a more interesting test of the JD's stack than the textbook fraud or credit-risk demos."*

Zero client name. Zero NDA risk. All neutral healthcare-domain vocabulary that any payer-side engineer recognizes.

## Status

Block 1 of the dev plan (multi-module skeleton) is complete with the domain-aware package names. Block 2 onward will fill in `member_record/`, `member_events/`, `care_decisioning/`, `payer_api/`, and `care_team_gateway/` against the schemas described above.
