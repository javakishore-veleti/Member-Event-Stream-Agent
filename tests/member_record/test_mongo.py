"""Offline tests for MongoStore using mongomock.

Covers index creation, member round-trip, idempotent event insert, risk
history retrieval, and tenant isolation.
"""
from __future__ import annotations

from datetime import datetime, date, timezone

import mongomock
import pytest

from member_event_stream_agent.member_record.mongo import MongoStore
from member_event_stream_agent.member_record.schemas import (
    LineOfBusiness,
    Member,
    RiskDimension,
    RiskScore,
)


@pytest.fixture()
def store() -> MongoStore:
    client = mongomock.MongoClient()
    s = MongoStore(client, db_name="mesa_test", payer_org_id="payer-A")
    s.ensure_indexes()
    return s


def _make_member(member_id: str = "M-001", payer_org_id: str = "payer-A") -> Member:
    return Member(
        payer_org_id=payer_org_id,
        member_id=member_id,
        plan_id="PLAN-MA-001",
        line_of_business=LineOfBusiness.MEDICARE,
        eligibility_start=date(2025, 1, 1),
        dob_year=1955,
        zip3="282",
        hcc_risk_score=1.34,
        pcp_provider_id="P-NPI-001",
    )


def _make_score(member_id: str = "M-001", payer_org_id: str = "payer-A") -> RiskScore:
    return RiskScore(
        payer_org_id=payer_org_id,
        risk_score_id="RS-001",
        member_id=member_id,
        dimension=RiskDimension.READMISSION,
        score=0.78,
        confidence=0.62,
        rationale="prior CHF admit 47 days ago, no PCP follow-up",
        citations=["EVT-100", "EVT-101"],
        model_version="v0.0.1-rules",
        produced_at=datetime(2026, 4, 8, 21, 0, tzinfo=timezone.utc),
    )


def test_indexes_are_created(store: MongoStore) -> None:
    members_indexes = store._db["members"].index_information()
    events_indexes = store._db["events"].index_information()
    assert "ux_members_tenant_member" in members_indexes
    assert "ux_events_tenant_event_id" in events_indexes


def test_save_and_get_member_round_trip(store: MongoStore) -> None:
    store.save_member(_make_member())

    fetched = store.get_member("M-001")
    assert fetched is not None
    assert fetched.member_id == "M-001"
    assert fetched.line_of_business == LineOfBusiness.MEDICARE
    assert fetched.dob_year == 1955


def test_get_member_returns_none_for_missing(store: MongoStore) -> None:
    assert store.get_member("does-not-exist") is None


def test_save_event_is_idempotent(store: MongoStore) -> None:
    event = {
        "event_id": "EVT-100",
        "member_id": "M-001",
        "family": "ENCOUNTER",
        "kind": "office_visit",
        "ts": datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc),
        "attributes": {"primary_dx_codes": ["E11.9"]},
    }

    assert store.save_event(event) is True
    # Second call with the same event_id must NOT insert again.
    assert store.save_event(event) is False

    recent = store.get_recent_events("M-001")
    assert len(recent) == 1
    assert recent[0]["event_id"] == "EVT-100"


def test_get_recent_events_orders_by_ts_desc(store: MongoStore) -> None:
    base = datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc)
    for i in range(3):
        store.save_event(
            {
                "event_id": f"EVT-{i}",
                "member_id": "M-001",
                "family": "PHARMACY",
                "kind": "rx_filled",
                "ts": base.replace(hour=9 + i),
                "attributes": {},
            },
        )

    recent = store.get_recent_events("M-001", limit=10)
    assert [e["event_id"] for e in recent] == ["EVT-2", "EVT-1", "EVT-0"]


def test_risk_history_filters_by_dimension(store: MongoStore) -> None:
    store.save_risk_score(_make_score())
    other = _make_score()
    other.risk_score_id = "RS-002"
    other.dimension = RiskDimension.CARE_GAP
    store.save_risk_score(other)

    history = store.get_risk_history("M-001", RiskDimension.READMISSION)
    assert len(history) == 1
    assert history[0].dimension == RiskDimension.READMISSION


def test_tenant_isolation_on_save_member(store: MongoStore) -> None:
    with pytest.raises(ValueError, match="payer_org_id"):
        store.save_member(_make_member(payer_org_id="payer-B"))


def test_tenant_isolation_on_get_event(store: MongoStore) -> None:
    # Write an event for tenant A.
    store.save_event(
        {
            "event_id": "EVT-A",
            "member_id": "M-001",
            "family": "ENCOUNTER",
            "kind": "office_visit",
            "ts": datetime(2026, 4, 1, tzinfo=timezone.utc),
        },
    )
    # Query the same db as tenant B — should see nothing.
    other = MongoStore(store._client, db_name="mesa_test", payer_org_id="payer-B")
    assert other.get_recent_events("M-001") == []
