from __future__ import annotations

from datetime import datetime, timezone

import pytest

from member_event_stream_agent.care_decisioning.base import PipelineCtx
from member_event_stream_agent.care_decisioning.triage import TriageAgent
from member_event_stream_agent.member_events.schemas import EventFamily, MemberEvent
from member_event_stream_agent.member_record.schemas import RiskDimension


def _ctx(family: EventFamily, kind: str) -> PipelineCtx:
    event = MemberEvent(
        event_id="E-1",
        member_id="M-1",
        family=family,
        kind=kind,
        ts=datetime(2026, 4, 8, tzinfo=timezone.utc),
        source_system="adt",
        attributes={},
        payload_hash="abc",
        received_at=datetime(2026, 4, 8, tzinfo=timezone.utc),
    )
    return PipelineCtx(event=event, payer_org_id="payer-A")


@pytest.mark.asyncio
async def test_triage_inpatient_discharge_to_readmission() -> None:
    ctx = await TriageAgent().run(_ctx(EventFamily.ENCOUNTER, "inpatient_discharge"))
    assert ctx.use_case == RiskDimension.READMISSION
    assert ctx.skip is False
    assert ctx.audit_trace[-1]["stage"] == "triage"
    assert ctx.audit_trace[-1]["use_case"] == "readmission"


@pytest.mark.asyncio
async def test_triage_rx_filled_to_polypharmacy() -> None:
    ctx = await TriageAgent().run(_ctx(EventFamily.PHARMACY, "rx_filled"))
    assert ctx.use_case == RiskDimension.POLYPHARMACY


@pytest.mark.asyncio
async def test_triage_prior_auth_to_pa_decision() -> None:
    ctx = await TriageAgent().run(_ctx(EventFamily.PHARMACY, "prior_auth_requested"))
    assert ctx.use_case == RiskDimension.PA_DECISION


@pytest.mark.asyncio
async def test_triage_office_visit_to_care_gap() -> None:
    ctx = await TriageAgent().run(_ctx(EventFamily.ENCOUNTER, "office_visit"))
    assert ctx.use_case == RiskDimension.CARE_GAP


@pytest.mark.asyncio
async def test_triage_unknown_combo_skips() -> None:
    ctx = await TriageAgent().run(_ctx(EventFamily.CARE_MGMT, "care_plan_created"))
    assert ctx.skip is True
    assert ctx.skip_reason is not None
    assert "no use case mapped" in ctx.skip_reason
