from __future__ import annotations

from datetime import date, datetime, timezone

import mongomock
import pytest

from member_event_stream_agent.care_decisioning.base import PipelineCtx
from member_event_stream_agent.care_decisioning.enrichment import EnrichmentAgent
from member_event_stream_agent.member_events.schemas import EventFamily, MemberEvent
from member_event_stream_agent.member_record.mongo import MongoStore
from member_event_stream_agent.member_record.schemas import LineOfBusiness, Member


@pytest.fixture()
def store() -> MongoStore:
    s = MongoStore(mongomock.MongoClient(), db_name="mesa_test", payer_org_id="payer-A")
    s.ensure_indexes()
    return s


def _event(member_id: str = "M-1") -> MemberEvent:
    return MemberEvent(
        event_id="E-1",
        member_id=member_id,
        family=EventFamily.ENCOUNTER,
        kind="inpatient_discharge",
        ts=datetime(2026, 4, 8, tzinfo=timezone.utc),
        source_system="adt",
        attributes={},
        payload_hash="abc",
        received_at=datetime(2026, 4, 8, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_enrichment_loads_member_and_recent_events(store: MongoStore) -> None:
    store.save_member(
        Member(
            payer_org_id="payer-A",
            member_id="M-1",
            plan_id="PLAN-1",
            line_of_business=LineOfBusiness.MEDICARE,
            eligibility_start=date(2025, 1, 1),
            dob_year=1955,
            zip3="282",
        ),
    )
    for i in range(3):
        store.save_event(
            {
                "event_id": f"E-prior-{i}",
                "member_id": "M-1",
                "family": "ENCOUNTER",
                "kind": "inpatient_admit",
                "ts": datetime(2026, 3, i + 1, tzinfo=timezone.utc),
                "attributes": {},
            },
        )

    ctx = PipelineCtx(event=_event(), payer_org_id="payer-A")
    ctx = await EnrichmentAgent(store).run(ctx)

    assert ctx.member is not None
    assert ctx.member.member_id == "M-1"
    assert len(ctx.recent_events) == 3
    assert ctx.audit_trace[-1]["stage"] == "enrichment"
    assert ctx.audit_trace[-1]["recent_events_count"] == 3


@pytest.mark.asyncio
async def test_enrichment_no_op_when_skipped(store: MongoStore) -> None:
    ctx = PipelineCtx(event=_event(), payer_org_id="payer-A", skip=True)
    ctx = await EnrichmentAgent(store).run(ctx)
    assert ctx.member is None
    assert ctx.recent_events == []
