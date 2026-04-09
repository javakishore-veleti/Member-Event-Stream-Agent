"""Tests for Rescorer + LateClaimRescoreWorker.

End-to-end shape:
    1. Seed a member and process a normal encounter event through the
       Pipeline so a RiskScore lands in CARE_GAP.
    2. A late claim arrives. Run it through LateClaimRescoreWorker.
    3. Assert the worker rescored CARE_GAP (the existing dimension) and
       a *second* RiskScore document landed for the same member/dimension,
       plus a fresh CaseFile tagged with the rescore model_version.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import mongomock
import pytest

from member_event_stream_agent.care_decisioning.pipeline import Pipeline
from member_event_stream_agent.care_decisioning.rescore import Rescorer
from member_event_stream_agent.member_events.late_claim_worker import (
    LateClaimRescoreWorker,
)
from member_event_stream_agent.member_events.schemas import EventFamily, MemberEvent
from member_event_stream_agent.member_record.mongo import MongoStore
from member_event_stream_agent.member_record.schemas import (
    LineOfBusiness,
    Member,
    RiskDimension,
)


def _store_with_member() -> MongoStore:
    store = MongoStore(mongomock.MongoClient(), "mesa_rescore", "t1")
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


def _event(family: EventFamily, kind: str, event_id: str = "E1") -> MemberEvent:
    now = datetime.now(tz=timezone.utc)
    return MemberEvent(
        event_id=event_id,
        member_id="M1",
        family=family,
        kind=kind,
        ts=now,
        source_system="claims",
        attributes={},
        payload_hash="hash",
        received_at=now,
    )


@pytest.mark.asyncio
async def test_rescorer_writes_fresh_score_and_case_file() -> None:
    store = _store_with_member()
    rescorer = Rescorer(store)

    ctx = await rescorer.rescore("M1", RiskDimension.CARE_GAP, trigger_event_id="claim-1")

    assert ctx.risk_score is not None
    assert ctx.disposition is not None
    [score_doc] = list(store._db["risk_scores"].find())
    assert score_doc["dimension"] == "care_gap"
    [case_file] = list(store._db["case_files"].find())
    assert case_file["model_version"] == "v0.0.1-rules-rescore"


@pytest.mark.asyncio
async def test_late_claim_worker_rescores_existing_dimensions() -> None:
    store = _store_with_member()
    pipeline = Pipeline(store)

    # 1. A normal office_visit lands -> CARE_GAP score persisted.
    await pipeline.process(_event(EventFamily.ENCOUNTER, "office_visit", "E1"))
    initial_scores = store._db["risk_scores"].count_documents({})
    initial_case_files = store._db["case_files"].count_documents({})
    assert initial_scores == 1
    assert "care_gap" in store.get_member_risk_dimensions("M1")

    # 2. A late claim arrives.
    worker = LateClaimRescoreWorker(store, Rescorer(store))
    rescored = await worker.handle(_event(EventFamily.CLAIM, "claim_received", "claim-late"))

    assert rescored == [RiskDimension.CARE_GAP]
    # 3. A second risk_score landed for CARE_GAP (rescore appended, not overwrote).
    care_gap_scores = list(
        store._db["risk_scores"].find({"member_id": "M1", "dimension": "care_gap"}),
    )
    assert len(care_gap_scores) == 2
    # 4. A fresh CaseFile tagged with the rescore model_version landed.
    rescore_case_files = list(
        store._db["case_files"].find({"model_version": "v0.0.1-rules-rescore"}),
    )
    assert len(rescore_case_files) == 1
    assert store._db["case_files"].count_documents({}) == initial_case_files + 1


@pytest.mark.asyncio
async def test_late_claim_worker_ignores_non_claim_events() -> None:
    store = _store_with_member()
    worker = LateClaimRescoreWorker(store, Rescorer(store))
    rescored = await worker.handle(_event(EventFamily.PHARMACY, "rx_filled"))
    assert rescored == []


@pytest.mark.asyncio
async def test_late_claim_worker_skips_fwa_to_avoid_double_write() -> None:
    """FWA is already handled by the main Pipeline's Triage on the same
    CLAIM event; the rescore worker must not duplicate it."""
    store = _store_with_member()
    pipeline = Pipeline(store)

    # Run a claim through the pipeline so FWA + (later) other dims accumulate.
    await pipeline.process(_event(EventFamily.CLAIM, "claim_received", "E1"))
    assert "fwa" in store.get_member_risk_dimensions("M1")

    worker = LateClaimRescoreWorker(store, Rescorer(store))
    rescored = await worker.handle(_event(EventFamily.CLAIM, "claim_received", "claim-late"))
    assert RiskDimension.FWA not in rescored
