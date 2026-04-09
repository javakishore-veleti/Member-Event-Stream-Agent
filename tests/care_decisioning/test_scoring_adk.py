"""AdkScoringAgent tests with the FakeLlmClient.

Covers three things:
    1. Happy path — the queued ScoringResponse round-trips into a RiskScore
       on the PipelineCtx, source tag in the audit trail says "adk".
    2. End-to-end pipeline swap — Pipeline(scoring_agent=AdkScoringAgent(...))
       processes one synthetic event against a mongomock store and lands a
       CaseFile, proving the seam in pipeline.py works.
    3. Fall-back path — when the LlmClient raises, the agent quietly delegates
       to the rule-based ScoringAgent and the audit trail records fallback=True.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import mongomock
import pytest

from member_event_stream_agent.care_decisioning.adk.llm import (
    FakeLlmClient,
    ScoringResponse,
)
from member_event_stream_agent.care_decisioning.adk.scoring_adk import AdkScoringAgent
from member_event_stream_agent.care_decisioning.base import PipelineCtx
from member_event_stream_agent.care_decisioning.pipeline import Pipeline
from member_event_stream_agent.member_events.schemas import EventFamily, MemberEvent
from member_event_stream_agent.member_record.mongo import MongoStore
from member_event_stream_agent.member_record.schemas import (
    LineOfBusiness,
    Member,
    RiskDimension,
)


def _event(member_id: str = "M1", kind: str = "office_visit") -> MemberEvent:
    return MemberEvent(
        event_id="E1",
        member_id=member_id,
        family=EventFamily.ENCOUNTER,
        kind=kind,
        ts=datetime.now(tz=timezone.utc),
        source_system="claims",
        attributes={},
        payload_hash="hash",
        received_at=datetime.now(tz=timezone.utc),
    )


@pytest.mark.asyncio
async def test_adk_scoring_happy_path() -> None:
    client = FakeLlmClient(
        scoring_responses=[
            ScoringResponse(score=0.82, rationale="prior admit pattern", citations=["E1"]),
        ],
    )
    agent = AdkScoringAgent(client)
    ctx = PipelineCtx(event=_event(), payer_org_id="t1", use_case=RiskDimension.READMISSION)

    out = await agent.run(ctx)

    assert out.risk_score is not None
    assert out.risk_score.score == pytest.approx(0.82)
    assert out.risk_score.dimension == RiskDimension.READMISSION
    assert out.risk_score.citations == ["E1"]
    assert any(t.get("source") == "adk" for t in out.audit_trace)
    assert client.scoring_calls and client.scoring_calls[0]["context"]["use_case"] == "readmission"


@pytest.mark.asyncio
async def test_adk_scoring_falls_back_on_error() -> None:
    client = FakeLlmClient(raise_on_next=True)  # no responses queued, raise immediately
    agent = AdkScoringAgent(client)
    ctx = PipelineCtx(event=_event(), payer_org_id="t1", use_case=RiskDimension.CARE_GAP)

    out = await agent.run(ctx)

    assert out.risk_score is not None  # rule-based fallback ran
    assert any(t.get("fallback") is True for t in out.audit_trace)


@pytest.mark.asyncio
async def test_pipeline_uses_injected_adk_scoring_agent() -> None:
    store = MongoStore(mongomock.MongoClient(), "mesa_adk", "t1")
    store.save_member(
        Member(
            payer_org_id="t1",
            member_id="M1",
            plan_id="P1",
            line_of_business=LineOfBusiness.COMMERCIAL,
            eligibility_start=date(2024, 1, 1),
            dob_year=1980,
            zip3="021",
        ),
    )
    client = FakeLlmClient(
        scoring_responses=[
            ScoringResponse(score=0.55, rationale="adk override", citations=["E1"]),
        ],
    )
    pipeline = Pipeline(store, scoring_agent=AdkScoringAgent(client))

    await pipeline.process(_event())

    assert store._db["case_files"].count_documents({}) == 1
    [score_doc] = list(store._db["risk_scores"].find())
    assert score_doc["rationale"] == "adk override"
    assert score_doc["model_version"] == "v0.1.0-adk"
