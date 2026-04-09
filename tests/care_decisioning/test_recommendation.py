from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from member_event_stream_agent.care_decisioning.base import PipelineCtx
from member_event_stream_agent.care_decisioning.recommendation import (
    RecommendationAgent,
)
from member_event_stream_agent.member_events.schemas import EventFamily, MemberEvent
from member_event_stream_agent.member_record.schemas import (
    DispositionAction,
    RiskDimension,
    RiskScore,
)


def _ctx(use_case: RiskDimension, score_value: float) -> PipelineCtx:
    event = MemberEvent(
        event_id="E-1",
        member_id="M-1",
        family=EventFamily.ENCOUNTER,
        kind="inpatient_discharge",
        ts=datetime(2026, 4, 8, tzinfo=timezone.utc),
        source_system="adt",
        attributes={},
        payload_hash="abc",
        received_at=datetime(2026, 4, 8, tzinfo=timezone.utc),
    )
    score = RiskScore(
        payer_org_id="payer-A",
        risk_score_id=str(uuid.uuid4()),
        member_id="M-1",
        dimension=use_case,
        score=score_value,
        confidence=0.5,
        rationale="test",
        citations=["E-1"],
        model_version="v0.0.1-rules",
        produced_at=datetime(2026, 4, 8, tzinfo=timezone.utc),
    )
    return PipelineCtx(
        event=event,
        payer_org_id="payer-A",
        use_case=use_case,
        risk_score=score,
    )


@pytest.mark.asyncio
async def test_high_readmission_score_notifies_care_manager() -> None:
    ctx = await RecommendationAgent().run(_ctx(RiskDimension.READMISSION, 0.75))
    assert ctx.disposition is not None
    assert ctx.disposition.action == DispositionAction.NOTIFY_CARE_MANAGER


@pytest.mark.asyncio
async def test_low_readmission_score_returns_none() -> None:
    ctx = await RecommendationAgent().run(_ctx(RiskDimension.READMISSION, 0.2))
    assert ctx.disposition is not None
    assert ctx.disposition.action == DispositionAction.NONE


@pytest.mark.asyncio
async def test_care_gap_above_threshold_opens_outreach() -> None:
    ctx = await RecommendationAgent().run(_ctx(RiskDimension.CARE_GAP, 0.5))
    assert ctx.disposition is not None
    assert ctx.disposition.action == DispositionAction.OPEN_OUTREACH


@pytest.mark.asyncio
async def test_pa_decision_always_queues_review() -> None:
    ctx = await RecommendationAgent().run(_ctx(RiskDimension.PA_DECISION, 0.1))
    assert ctx.disposition is not None
    assert ctx.disposition.action == DispositionAction.QUEUE_PA_REVIEW


@pytest.mark.asyncio
async def test_polypharmacy_high_score_proposes_intervention() -> None:
    ctx = await RecommendationAgent().run(_ctx(RiskDimension.POLYPHARMACY, 0.8))
    assert ctx.disposition is not None
    assert ctx.disposition.action == DispositionAction.PROPOSE_INTERVENTION
