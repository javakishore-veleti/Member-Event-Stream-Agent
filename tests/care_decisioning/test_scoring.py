from __future__ import annotations

from datetime import datetime, timezone

import pytest

from member_event_stream_agent.care_decisioning.base import PipelineCtx
from member_event_stream_agent.care_decisioning.scoring import ScoringAgent
from member_event_stream_agent.member_events.schemas import EventFamily, MemberEvent
from member_event_stream_agent.member_record.schemas import RiskDimension


def _ctx(use_case: RiskDimension | None, recent: list[dict] | None = None) -> PipelineCtx:
    event = MemberEvent(
        event_id="E-current",
        member_id="M-1",
        family=EventFamily.ENCOUNTER,
        kind="inpatient_discharge",
        ts=datetime(2026, 4, 8, tzinfo=timezone.utc),
        source_system="adt",
        attributes={},
        payload_hash="abc",
        received_at=datetime(2026, 4, 8, tzinfo=timezone.utc),
    )
    return PipelineCtx(
        event=event,
        payer_org_id="payer-A",
        use_case=use_case,
        recent_events=recent or [],
    )


@pytest.mark.asyncio
async def test_scoring_readmission_increases_with_prior_admits() -> None:
    no_prior = await ScoringAgent().run(_ctx(RiskDimension.READMISSION, recent=[]))
    with_prior = await ScoringAgent().run(
        _ctx(
            RiskDimension.READMISSION,
            recent=[
                {"event_id": f"E-{i}", "family": "ENCOUNTER", "kind": "inpatient_admit"}
                for i in range(2)
            ],
        ),
    )
    assert no_prior.risk_score is not None
    assert with_prior.risk_score is not None
    assert with_prior.risk_score.score > no_prior.risk_score.score
    assert "E-current" in with_prior.risk_score.citations


@pytest.mark.asyncio
async def test_scoring_polypharmacy_counts_recent_rx_filled() -> None:
    ctx = _ctx(
        RiskDimension.POLYPHARMACY,
        recent=[
            {"event_id": f"RX-{i}", "family": "PHARMACY", "kind": "rx_filled"}
            for i in range(4)
        ],
    )
    out = await ScoringAgent().run(ctx)
    assert out.risk_score is not None
    assert out.risk_score.score >= 0.5
    assert any("RX-" in c for c in out.risk_score.citations)


@pytest.mark.asyncio
async def test_scoring_skips_when_no_use_case() -> None:
    ctx = _ctx(use_case=None)
    ctx.skip = True
    out = await ScoringAgent().run(ctx)
    assert out.risk_score is None
    assert out.audit_trace[-1]["stage"] == "scoring"
    assert out.audit_trace[-1].get("skipped") is True


@pytest.mark.asyncio
async def test_scoring_records_audit_entry() -> None:
    out = await ScoringAgent().run(_ctx(RiskDimension.CARE_GAP))
    assert out.risk_score is not None
    last = out.audit_trace[-1]
    assert last["stage"] == "scoring"
    assert last["dimension"] == "care_gap"
    assert "score" in last
