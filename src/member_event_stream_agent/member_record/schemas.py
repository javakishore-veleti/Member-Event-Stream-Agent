"""Pydantic v2 persistence schemas for the member_record (Member 360) store.

These models are the canonical shapes the longitudinal record holds. Source
systems (claims, PBM, ADT, lab vendors, care management) normalize into the
unified MemberEvent envelope (defined in member_events/) and the typed
entities defined here.

Convention: fields that carry PHI are tagged via Field(json_schema_extra={"phi": True}).
The PHI-aware structlog processor and the care_team_gateway redaction layer
read that metadata to decide what to strip or hash on egress. No code in this
module performs redaction itself — it only declares the policy.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class LineOfBusiness(str, Enum):
    COMMERCIAL = "commercial"
    MEDICARE = "medicare"
    MEDICAID = "medicaid"
    DSNP = "dsnp"


class EncounterType(str, Enum):
    OFFICE = "office"
    ED = "ed"
    INPATIENT = "inpatient"
    TELEHEALTH = "telehealth"


class AdjudicationStatus(str, Enum):
    RECEIVED = "received"
    PAID = "paid"
    DENIED = "denied"
    REVERSED = "reversed"


class EventFamily(str, Enum):
    """The shared event-family enum, also re-exported by member_events."""

    ELIGIBILITY = "ELIGIBILITY"
    ENCOUNTER = "ENCOUNTER"
    CLAIM = "CLAIM"
    PHARMACY = "PHARMACY"
    LAB = "LAB"
    CARE_MGMT = "CARE_MGMT"


class RiskDimension(str, Enum):
    READMISSION = "readmission"
    CARE_GAP = "care_gap"
    ADHERENCE = "adherence"
    POLYPHARMACY = "polypharmacy"
    FWA = "fwa"
    PA_DECISION = "pa_decision"


class DispositionAction(str, Enum):
    NONE = "none"
    NOTIFY_CARE_MANAGER = "notify_care_manager"
    OPEN_OUTREACH = "open_outreach"
    QUEUE_PA_REVIEW = "queue_pa_review"
    PROPOSE_INTERVENTION = "propose_intervention"
    ESCALATE_FWA = "escalate_fwa"
    DRAFT_PA_RESPONSE = "draft_pa_response"


# ---------------------------------------------------------------------------
# Persistence base
# ---------------------------------------------------------------------------


class PayerScopedModel(BaseModel):
    """Mixin parent for every model that lives in a payer-scoped collection.

    Every record carries `payer_org_id` so MongoStore can enforce tenant
    isolation at the query layer.
    """

    model_config = ConfigDict(extra="allow")

    payer_org_id: str = Field(description="Tenant identifier; enforced at MongoStore level.")


# ---------------------------------------------------------------------------
# Member 360 entities
# ---------------------------------------------------------------------------


class Member(PayerScopedModel):
    member_id: str
    plan_id: str
    line_of_business: LineOfBusiness
    eligibility_start: date
    eligibility_end: date | None = None
    dob_year: int = Field(json_schema_extra={"phi": True}, ge=1900, le=2100)
    zip3: str = Field(json_schema_extra={"phi": True}, min_length=3, max_length=3)
    hcc_risk_score: float | None = None
    pcp_provider_id: str | None = None
    consent_flags: dict[str, bool] = Field(default_factory=dict)


class Provider(PayerScopedModel):
    provider_id: str
    npi_hash: str = Field(json_schema_extra={"phi": True})
    specialty: str
    network_status: str  # "in_network" | "out_of_network" | "unknown"


class Encounter(PayerScopedModel):
    encounter_id: str
    member_id: str
    provider_id: str
    encounter_type: EncounterType
    service_date: date
    primary_dx_codes: list[str] = Field(default_factory=list)  # ICD-10
    place_of_service: str | None = None
    ts: datetime


class ClaimLine(PayerScopedModel):
    claim_id: str
    line_id: str
    member_id: str
    provider_id: str
    service_date: date
    dx_codes: list[str] = Field(default_factory=list)  # ICD-10
    procedure_code: str  # CPT / HCPCS
    billed_amount: float
    allowed_amount: float
    paid_amount: float
    adjudication_status: AdjudicationStatus
    ts: datetime


class MedicationFill(PayerScopedModel):
    fill_id: str
    member_id: str
    prescriber_id: str
    ndc: str  # National Drug Code
    days_supply: int = Field(ge=0)
    fill_date: date
    refills_remaining: int = Field(ge=0)
    ts: datetime


class LabResult(PayerScopedModel):
    result_id: str
    member_id: str
    loinc_code: str  # LOINC test code
    value: float | str  # numeric or coded
    unit: str | None = None
    observed_at: datetime
    abnormal_flag: bool = False
    ts: datetime


# ---------------------------------------------------------------------------
# Agent pipeline outputs
# ---------------------------------------------------------------------------


class RiskScore(PayerScopedModel):
    risk_score_id: str
    member_id: str
    dimension: RiskDimension
    measure_id: str | None = None  # e.g. "HEDIS-BCS-E" for care_gap dimension
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    citations: list[str] = Field(default_factory=list)  # event_id references
    model_version: str
    produced_at: datetime
    valid_until: datetime | None = None


class Disposition(PayerScopedModel):
    disposition_id: str
    member_id: str
    risk_score_id: str
    action: DispositionAction
    notes: str | None = None
    produced_at: datetime


class CaseFile(PayerScopedModel):
    """Immutable HIPAA audit record. One per Disposition.

    The agent_trace captures the input/output of each pipeline stage so
    a compliance reviewer can reconstruct exactly how a decision was made.
    """

    case_file_id: str
    member_id: str
    disposition_id: str
    inputs_hash: str  # SHA-256 of the inputs that drove the decision
    agent_trace: list[dict[str, Any]] = Field(default_factory=list)
    model_version: str
    reviewer_id: str | None = None  # set when a human reviews / overrides
    phi_access_log: list[dict[str, Any]] = Field(default_factory=list)
    produced_at: datetime
    closed_at: datetime | None = None
