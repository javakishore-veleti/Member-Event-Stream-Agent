"""Tool-level tests for care_team_gateway. Calls tools.py functions directly
so we exercise auth + scope + redaction + audit without needing a wire MCP
server. The MongoStore here is backed by mongomock so the suite stays offline.
"""
from __future__ import annotations

from datetime import date

import mongomock
import pytest

from member_event_stream_agent.care_team_gateway import tools as gw_tools
from member_event_stream_agent.care_team_gateway.auth import AuthError
from member_event_stream_agent.member_record.mongo import MongoStore
from member_event_stream_agent.member_record.schemas import LineOfBusiness, Member

PAYER = "test-payer"
TOKEN = "dev-token"  # matches Settings default


@pytest.fixture
def store() -> MongoStore:
    s = MongoStore(mongomock.MongoClient(), "mesa_test", PAYER)
    s.save_member(
        Member(
            payer_org_id=PAYER,
            member_id="M1",
            plan_id="P1",
            line_of_business=LineOfBusiness.COMMERCIAL,
            eligibility_start=date(2024, 1, 1),
            dob_year=1980,
            zip3="021",
        ),
    )
    s.save_event(
        {
            "event_id": "E1",
            "member_id": "M1",
            "family": "ENCOUNTER",
            "kind": "office_visit",
            "ts": "2025-01-01T00:00:00+00:00",
            "source_system": "claims",
            "attributes": {"secret": "do-not-leak"},
        },
    )
    return s


def test_member_lookup_redacts_phi(store: MongoStore) -> None:
    out = gw_tools.member_lookup(
        "M1", store=store, token=TOKEN, scope="care_manager", caller_id="alice",
    )
    assert out["found"] is True
    member = out["member"]
    assert member["dob_year"] == gw_tools.REDACTED
    assert member["zip3"] == gw_tools.REDACTED
    assert member["member_id"] == "M1"  # non-PHI passes through


def test_member_lookup_not_found(store: MongoStore) -> None:
    out = gw_tools.member_lookup(
        "missing", store=store, token=TOKEN, scope="quality", caller_id="bob",
    )
    assert out == {"found": False, "member_id": "missing"}


def test_recent_events_strips_attributes(store: MongoStore) -> None:
    out = gw_tools.recent_events(
        "M1", store=store, token=TOKEN, scope="um", caller_id="carol",
    )
    assert out["count"] == 1
    event = out["events"][0]
    assert "attributes" not in event
    assert event["event_id"] == "E1"


def test_bad_token_rejected(store: MongoStore) -> None:
    with pytest.raises(AuthError):
        gw_tools.member_lookup(
            "M1", store=store, token="wrong", scope="care_manager", caller_id="alice",
        )


def test_bad_scope_rejected(store: MongoStore) -> None:
    with pytest.raises(AuthError):
        gw_tools.member_lookup(
            "M1", store=store, token=TOKEN, scope="not_a_persona", caller_id="alice",
        )
