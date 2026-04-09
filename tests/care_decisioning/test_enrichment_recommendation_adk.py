"""Tests for AdkEnrichmentAgent and AdkRecommendationAgent.

Covers happy paths and the fall-back contracts. End-to-end pipeline test
constructs Pipeline with all four ADK variants wired in and asserts a
CaseFile lands with the LLM-chosen disposition action.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import mongomock
import pytest

from member_event_stream_agent.care_decisioning.adk.enrichment_adk import AdkEnrichmentAgent
from member_event_stream_agent.care_decisioning.adk.llm import (
    FakeLlmClient,
    NarrativeResponse,
    RecommendationResponse,
    ScoringResponse,
    TriageResponse,
)
from member_event_stream_agent.care_decisioning.adk.recommendation_adk import (
    AdkRecommendationAgent,
)
from member_event_stream_agent.care_decisioning.adk.scoring_adk import AdkScoringAgent
from member_event_stream_agent.care_decisioning.adk.triage_adk import AdkTriageAgent
from member_event_stream_agent.care_decisioning.base import PipelineCtx
from member_event_stream_agent.care_decisioning.pipeline import Pipeline
from member_event_stream_agent.member_events.schemas import EventFamily, MemberEvent
from member_event_stream_agent.member_record.mongo import MongoStore
from member_event_stream_agent.member_record.schemas import (
    DispositionAction,
    LineOfBusiness,
    Member,
    RiskDimension,
    RiskScore,
)


def _event() -> MemberEvent:
    return MemberEvent(
        event_id="E1",
        member_id="M1",
        family=EventFamily.ENCOUNTER,
        kind="office_visit",
        ts=datetime.now(tz=timezone.utc),
        source_system="claims",
        attributes={},
        payload_hash="hash",
        received_at=datetime.now(tz=timezone.utc),
    )


def _store_with_member() -> MongoStore:
    store = MongoStore(mongomock.MongoClient(), "mesa_adk4", "t1")
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
    return store


@pytest.mark.asyncio
async def test_adk_enrichment_attaches_narrative() -> None:
    store = _store_with_member()
    client = FakeLlmClient(
        narrative_responses=[NarrativeResponse(narrative="Recent office visit; no admits.")],
    )
    agent = AdkEnrichmentAgent(store, client)
    ctx = PipelineCtx(event=_event(), payer_org_id="t1", use_case=RiskDimension.CARE_GAP)

    out = await agent.run(ctx)

    assert out.member is not None  # DB read still happened
    assert out.narrative == "Recent office visit; no admits."
    assert any(t.get("source") == "adk" for t in out.audit_trace)


@pytest.mark.asyncio
async def test_adk_enrichment_falls_back_silently_on_error() -> None:
    store = _store_with_member()
    client = FakeLlmClient(raise_on_next=True)
    agent = AdkEnrichmentAgent(store, client)
    ctx = PipelineCtx(event=_event(), payer_org_id="t1", use_case=RiskDimension.CARE_GAP)

    out = await agent.run(ctx)

    assert out.member is not None
    assert out.narrative is None
    assert any(t.get("fallback") is True for t in out.audit_trace)


@pytest.mark.asyncio
async def test_adk_recommendation_picks_action() -> None:
    client = FakeLlmClient(
        recommendation_responses=[
            RecommendationResponse(action="open_outreach", notes="gap is open"),
        ],
    )
    agent = AdkRecommendationAgent(client)
    ctx = PipelineCtx(event=_event(), payer_org_id="t1", use_case=RiskDimension.CARE_GAP)
    ctx.risk_score = RiskScore(
        payer_org_id="t1",
        risk_score_id="rs-1",
        member_id="M1",
        dimension=RiskDimension.CARE_GAP,
        score=0.6,
        confidence=0.7,
        rationale="r",
        citations=["E1"],
        model_version="v",
        produced_at=datetime.now(tz=timezone.utc),
    )

    out = await agent.run(ctx)

    assert out.disposition is not None
    assert out.disposition.action == DispositionAction.OPEN_OUTREACH
    assert out.disposition.notes == "gap is open"


@pytest.mark.asyncio
async def test_adk_recommendation_unknown_action_falls_back() -> None:
    client = FakeLlmClient(
        recommendation_responses=[RecommendationResponse(action="not-a-real-action")],
    )
    agent = AdkRecommendationAgent(client)
    ctx = PipelineCtx(event=_event(), payer_org_id="t1", use_case=RiskDimension.CARE_GAP)
    ctx.risk_score = RiskScore(
        payer_org_id="t1",
        risk_score_id="rs-1",
        member_id="M1",
        dimension=RiskDimension.CARE_GAP,
        score=0.6,
        confidence=0.7,
        rationale="r",
        citations=["E1"],
        model_version="v",
        produced_at=datetime.now(tz=timezone.utc),
    )

    out = await agent.run(ctx)

    assert out.disposition is not None  # rule fall-back chose OPEN_OUTREACH (score 0.6 >= 0.4)
    assert out.disposition.action == DispositionAction.OPEN_OUTREACH
    assert any(t.get("fallback") is True for t in out.audit_trace)


@pytest.mark.asyncio
async def test_pipeline_all_adk_variants_wired() -> None:
    store = _store_with_member()
    client = FakeLlmClient(
        triage_responses=[TriageResponse(use_case="care_gap", rationale="adk routed")],
        narrative_responses=[NarrativeResponse(narrative="No prior admits.")],
        scoring_responses=[
            ScoringResponse(score=0.55, rationale="adk score", citations=["E1"]),
        ],
        recommendation_responses=[
            RecommendationResponse(action="open_outreach", notes="adk action"),
        ],
    )
    pipeline = Pipeline(
        store,
        triage_agent=AdkTriageAgent(client),
        enrichment_agent=AdkEnrichmentAgent(store, client),
        scoring_agent=AdkScoringAgent(client),
        recommendation_agent=AdkRecommendationAgent(client),
    )

    await pipeline.process(_event())

    [case_file] = list(store._db["case_files"].find())
    assert case_file["model_version"] == "v0.0.1-rules"  # pipeline-level tag
    [disposition] = list(store._db["dispositions"].find())
    assert disposition["action"] == DispositionAction.OPEN_OUTREACH.value
    assert disposition["notes"] == "adk action"
