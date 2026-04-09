"""AdkTriageAgent tests with the FakeLlmClient.

Covers:
    1. Happy path — queued TriageResponse with a valid use_case lands as
       ctx.use_case and skip stays False.
    2. None / unknown use_case — skip is set, downstream stages no-op.
    3. LLM error — falls back to the rule-based TriageAgent.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from member_event_stream_agent.care_decisioning.adk.llm import (
    FakeLlmClient,
    TriageResponse,
)
from member_event_stream_agent.care_decisioning.adk.triage_adk import AdkTriageAgent
from member_event_stream_agent.care_decisioning.base import PipelineCtx
from member_event_stream_agent.member_events.schemas import EventFamily, MemberEvent
from member_event_stream_agent.member_record.schemas import RiskDimension


def _event(kind: str = "office_visit") -> MemberEvent:
    return MemberEvent(
        event_id="E1",
        member_id="M1",
        family=EventFamily.ENCOUNTER,
        kind=kind,
        ts=datetime.now(tz=timezone.utc),
        source_system="claims",
        attributes={},
        payload_hash="hash",
        received_at=datetime.now(tz=timezone.utc),
    )


@pytest.mark.asyncio
async def test_adk_triage_classifies_use_case() -> None:
    client = FakeLlmClient(
        triage_responses=[TriageResponse(use_case="readmission", rationale="prior admit")],
    )
    agent = AdkTriageAgent(client)
    ctx = PipelineCtx(event=_event(), payer_org_id="t1")

    out = await agent.run(ctx)

    assert out.use_case == RiskDimension.READMISSION
    assert out.skip is False
    assert any(t.get("source") == "adk" for t in out.audit_trace)


@pytest.mark.asyncio
async def test_adk_triage_skips_when_use_case_unknown() -> None:
    client = FakeLlmClient(
        triage_responses=[TriageResponse(use_case="not-a-dimension", rationale="noise")],
    )
    agent = AdkTriageAgent(client)
    ctx = PipelineCtx(event=_event(), payer_org_id="t1")

    out = await agent.run(ctx)

    assert out.skip is True
    assert out.use_case is None


@pytest.mark.asyncio
async def test_adk_triage_falls_back_on_error() -> None:
    client = FakeLlmClient(raise_on_next=True)
    agent = AdkTriageAgent(client)
    # office_visit -> CARE_GAP via the rule-based fall-back
    ctx = PipelineCtx(event=_event(kind="office_visit"), payer_org_id="t1")

    out = await agent.run(ctx)

    assert out.use_case == RiskDimension.CARE_GAP
    assert any(t.get("fallback") is True for t in out.audit_trace)
