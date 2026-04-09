"""Smoke tests that the persistence schemas compile and round-trip cleanly."""
from __future__ import annotations

from datetime import date, datetime, timezone

from member_event_stream_agent.member_record.schemas import (
    AdjudicationStatus,
    CaseFile,
    ClaimLine,
    Disposition,
    DispositionAction,
    Encounter,
    EncounterType,
    EventFamily,
    LabResult,
    LineOfBusiness,
    MedicationFill,
    Member,
    Provider,
    RiskDimension,
    RiskScore,
)


def test_member_phi_metadata_is_declared() -> None:
    schema = Member.model_json_schema()
    assert schema["properties"]["dob_year"].get("phi") is True
    assert schema["properties"]["zip3"].get("phi") is True


def test_all_typed_entities_construct() -> None:
    now = datetime(2026, 4, 8, tzinfo=timezone.utc)
    today = date(2026, 4, 8)

    Member(
        payer_org_id="payer-A",
        member_id="M-1",
        plan_id="PLAN-1",
        line_of_business=LineOfBusiness.COMMERCIAL,
        eligibility_start=today,
        dob_year=1980,
        zip3="282",
    )
    Provider(
        payer_org_id="payer-A",
        provider_id="P-1",
        npi_hash="hashed",
        specialty="cardiology",
        network_status="in_network",
    )
    Encounter(
        payer_org_id="payer-A",
        encounter_id="E-1",
        member_id="M-1",
        provider_id="P-1",
        encounter_type=EncounterType.OFFICE,
        service_date=today,
        primary_dx_codes=["I10"],
        ts=now,
    )
    ClaimLine(
        payer_org_id="payer-A",
        claim_id="C-1",
        line_id="L-1",
        member_id="M-1",
        provider_id="P-1",
        service_date=today,
        dx_codes=["I10"],
        procedure_code="99213",
        billed_amount=200.0,
        allowed_amount=120.0,
        paid_amount=100.0,
        adjudication_status=AdjudicationStatus.PAID,
        ts=now,
    )
    MedicationFill(
        payer_org_id="payer-A",
        fill_id="F-1",
        member_id="M-1",
        prescriber_id="P-1",
        ndc="00071015523",
        days_supply=30,
        fill_date=today,
        refills_remaining=2,
        ts=now,
    )
    LabResult(
        payer_org_id="payer-A",
        result_id="L-1",
        member_id="M-1",
        loinc_code="4548-4",  # Hemoglobin A1c
        value=7.2,
        unit="%",
        observed_at=now,
        ts=now,
    )
    score = RiskScore(
        payer_org_id="payer-A",
        risk_score_id="RS-1",
        member_id="M-1",
        dimension=RiskDimension.CARE_GAP,
        measure_id="HEDIS-CDC-HbA1c",
        score=0.42,
        confidence=0.71,
        rationale="A1c last measured 14 months ago",
        citations=["EVT-1"],
        model_version="v0.0.1-rules",
        produced_at=now,
    )
    disposition = Disposition(
        payer_org_id="payer-A",
        disposition_id="D-1",
        member_id="M-1",
        risk_score_id="RS-1",
        action=DispositionAction.OPEN_OUTREACH,
        produced_at=now,
    )
    CaseFile(
        payer_org_id="payer-A",
        case_file_id="CF-1",
        member_id="M-1",
        disposition_id="D-1",
        inputs_hash="abc123",
        agent_trace=[{"stage": "triage", "out": "care_gap"}],
        model_version="v0.0.1-rules",
        produced_at=now,
    )

    # event family enum is exported here too
    assert EventFamily.CLAIM.value == "CLAIM"
    assert score.dimension == RiskDimension.CARE_GAP
    assert disposition.action == DispositionAction.OPEN_OUTREACH


def test_member_serializes_to_json_safe_dict() -> None:
    m = Member(
        payer_org_id="payer-A",
        member_id="M-1",
        plan_id="PLAN-1",
        line_of_business=LineOfBusiness.MEDICAID,
        eligibility_start=date(2026, 1, 1),
        dob_year=1990,
        zip3="282",
    )
    d = m.model_dump(mode="json")
    assert d["line_of_business"] == "medicaid"
    assert d["eligibility_start"] == "2026-01-01"
