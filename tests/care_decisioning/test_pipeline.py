"""End-to-end test for the care_decisioning Pipeline.

Feeds a synthetic inpatient_discharge event through the full pipeline
against a mongomock-backed MongoStore, then asserts that the RiskScore,
Disposition, and immutable CaseFile all landed in the store and that
the CaseFile carries the full agent_trace.
"""
from __future__ import annotations

from datetime import datetime, timezone

import mongomock
import pytest

from member_event_stream_agent.care_decisioning.pipeline import Pipeline
from member_event_stream_agent.member_events.schemas import EventFamily, MemberEvent
from member_event_stream_agent.member_record.mongo import MongoStore
from member_event_stream_agent.member_record.schemas import (
    DispositionAction,
    RiskDimension,
)


@pytest.fixture()
def store() -> MongoStore:
    s = MongoStore(mongomock.MongoClient(), db_name="mesa_test", payer_org_id="payer-A")
    s.ensure_indexes()
    return s


def _discharge_event() -> MemberEvent:
    return MemberEvent(
        event_id="E-DISCHARGE-1",
        member_id="M-1",
        family=EventFamily.ENCOUNTER,
        kind="inpatient_discharge",
        ts=datetime(2026, 4, 8, 9, 0, tzinfo=timezone.utc),
        source_system="adt",
        attributes={"primary_dx_codes": ["I50.9"]},
        payload_hash="hash-discharge-1",
        received_at=datetime(2026, 4, 8, 9, 0, 1, tzinfo=timezone.utc),
    )


def _seed_prior_admits(store: MongoStore, n: int) -> None:
    for i in range(n):
        store.save_event(
            {
                "event_id": f"E-PRIOR-{i}",
                "member_id": "M-1",
                "family": "ENCOUNTER",
                "kind": "inpatient_admit",
                "ts": datetime(2026, 3, i + 1, tzinfo=timezone.utc),
                "attributes": {},
            },
        )


@pytest.mark.asyncio
async def test_pipeline_end_to_end_persists_score_disposition_and_case_file(
    store: MongoStore,
) -> None:
    # Seed two prior inpatient admits so the readmission heuristic clears
    # the 0.6 threshold and the recommendation lands on notify_care_manager.
    _seed_prior_admits(store, n=2)

    pipeline = Pipeline(store)
    ctx = await pipeline.process(_discharge_event())

    # ----- in-memory ctx ----------------------------------------------
    assert ctx.skip is False
    assert ctx.use_case == RiskDimension.READMISSION
    assert ctx.risk_score is not None
    assert ctx.risk_score.score >= 0.6
    assert ctx.disposition is not None
    assert ctx.disposition.action == DispositionAction.NOTIFY_CARE_MANAGER

    # ----- RiskScore landed in mongo via get_risk_history -------------
    history = store.get_risk_history("M-1", RiskDimension.READMISSION)
    assert len(history) == 1
    assert history[0].risk_score_id == ctx.risk_score.risk_score_id
    assert "E-DISCHARGE-1" in history[0].citations

    # ----- Disposition landed in mongo --------------------------------
    dispositions = list(store._db["dispositions"].find({"member_id": "M-1"}))
    assert len(dispositions) == 1
    assert dispositions[0]["action"] == "notify_care_manager"

    # ----- CaseFile landed and carries agent_trace --------------------
    case_files = list(store._db["case_files"].find({"member_id": "M-1"}))
    assert len(case_files) == 1
    case = case_files[0]
    assert case["disposition_id"] == ctx.disposition.disposition_id
    assert case["model_version"] == "v0.0.1-rules"
    assert case["inputs_hash"]
    stages = [t["stage"] for t in case["agent_trace"]]
    assert stages == ["triage", "enrichment", "scoring", "recommendation"]

    # ----- the inbound event itself was persisted (idempotent) --------
    recent = store.get_recent_events("M-1", limit=10)
    assert any(e["event_id"] == "E-DISCHARGE-1" for e in recent)


@pytest.mark.asyncio
async def test_pipeline_skipped_event_writes_no_outputs(store: MongoStore) -> None:
    # CARE_MGMT/care_plan_created has no triage rule -> ctx.skip = True
    event = MemberEvent(
        event_id="E-SKIP",
        member_id="M-2",
        family=EventFamily.CARE_MGMT,
        kind="care_plan_created",
        ts=datetime(2026, 4, 8, tzinfo=timezone.utc),
        source_system="cm-platform",
        attributes={},
        payload_hash="hash-skip",
        received_at=datetime(2026, 4, 8, tzinfo=timezone.utc),
    )

    ctx = await Pipeline(store).process(event)

    assert ctx.skip is True
    assert ctx.risk_score is None
    assert ctx.disposition is None
    assert list(store._db["risk_scores"].find()) == []
    assert list(store._db["dispositions"].find()) == []
    assert list(store._db["case_files"].find()) == []
    # The event itself was still persisted (we want every event in the record).
    assert any(e["event_id"] == "E-SKIP" for e in store.get_recent_events("M-2"))


@pytest.mark.asyncio
async def test_pipeline_event_save_is_idempotent(store: MongoStore) -> None:
    pipeline = Pipeline(store)
    event = _discharge_event()

    await pipeline.process(event)
    await pipeline.process(event)

    recent = store.get_recent_events("M-1", limit=10)
    discharge_count = sum(1 for e in recent if e["event_id"] == "E-DISCHARGE-1")
    assert discharge_count == 1
