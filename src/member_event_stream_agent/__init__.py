"""member_event_stream_agent — Health Plan Member Event Platform.

A real-time, event-driven member event platform from a health insurance payer
(MCO / PBM / managed care org) perspective. Ingests eligibility, encounter,
claim, pharmacy, lab, and care-management events for plan members; runs them
through a multi-agent decisioning pipeline; persists every disposition with
HIPAA-grade audit trail; and exposes scoped investigative tools to clinical
and operational analysts via an MCP gateway.

Subpackages
-----------
member_events       — Kafka consumer / producer, raw + normalized event schemas
                      (ELIGIBILITY, ENCOUNTER, CLAIM, PHARMACY, LAB, CARE_MGMT),
                      and the source-system normalizer.
care_decisioning    — Multi-agent decisioning pipeline:
                          Triage → Enrichment → Scoring → Recommendation
                      Implements HEDIS / Stars care gap closure, 30-day
                      readmission risk, polypharmacy & DDI, prior-authorization
                      triage, and FWA pattern detection.
member_record       — MongoDB-backed longitudinal member record (the payer's
                      "Member 360"): Member, Encounter, ClaimLine, MedicationFill,
                      LabResult, RiskScore, Disposition, CaseFile, plus indexes
                      and aggregation queries.
payer_api           — FastAPI surface for clinical and operational staff:
                      member lookup, panel views, cohort queries, case files,
                      health and version endpoints.
care_team_gateway   — FastMCP server exposing investigative and case-management
                      tools to LLM clients used by care managers, utilization
                      managers, clinical pharmacists, quality/HEDIS analysts,
                      and FWA investigators. Auth and per-tool scope enforced;
                      every call audit-logged for HIPAA.

See README_HealthCare.md for the full domain model, named use cases, personas,
and production-grade NFRs.
"""

__version__ = "0.1.0"
