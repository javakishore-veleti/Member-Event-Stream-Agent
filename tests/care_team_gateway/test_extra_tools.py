"""Tests for the second wave of MCP tools.

Covers pa_queue, panel_overview, cohort_overview, and related_entities at
the tool-function layer (test_server.py already covers the FastMCP wire
path for member_lookup, so we keep these focused on logic + scope rules).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import mongomock
import pytest

from member_event_stream_agent.care_team_gateway import tools as gw_tools
from member_event_stream_agent.care_team_gateway.auth import AuthError
from member_event_stream_agent.member_record.mongo import MongoStore
from member_event_stream_agent.member_record.schemas import (
    Disposition,
    DispositionAction,
    LineOfBusiness,
    Member,
    RiskDimension,
    RiskScore,
)

PAYER = "test-payer"
TOKEN = "dev-token"


def _store() -> MongoStore:
    return MongoStore(mongomock.MongoClient(), "mesa_extra", PAYER)


def _make_member(member_id: str, pcp: str | None = None) -> Member:
    return Member(
        payer_org_id=PAYER,
        member_id=member_id,
        plan_id="P1",
        line_of_business=LineOfBusiness.COMMERCIAL,
        eligibility_start=date(2024, 1, 1),
        dob_year=1980,
        zip3="021",
        pcp_provider_id=pcp,
    )


def _make_score(member_id: str, dim: RiskDimension, score: float) -> RiskScore:
    return RiskScore(
        payer_org_id=PAYER,
        risk_score_id=f"rs-{member_id}-{dim.value}",
        member_id=member_id,
        dimension=dim,
        score=score,
        confidence=0.7,
        rationale="r",
        citations=[],
        model_version="v",
        produced_at=datetime.now(tz=timezone.utc),
    )


def _make_disposition(member_id: str, action: DispositionAction) -> Disposition:
    return Disposition(
        payer_org_id=PAYER,
        disposition_id=f"d-{member_id}-{action.value}",
        member_id=member_id,
        risk_score_id=f"rs-{member_id}",
        action=action,
        produced_at=datetime.now(tz=timezone.utc),
    )


# ---------------------------------------------------------------------------
# pa_queue
# ---------------------------------------------------------------------------


def test_pa_queue_returns_open_actions_only() -> None:
    store = _store()
    store.save_disposition(_make_disposition("M1", DispositionAction.QUEUE_PA_REVIEW))
    store.save_disposition(_make_disposition("M2", DispositionAction.PROPOSE_INTERVENTION))
    store.save_disposition(_make_disposition("M3", DispositionAction.NONE))  # ignored

    out = gw_tools.pa_queue(
        store=store, token=TOKEN, scope="um", caller_id="alice",
    )

    assert out["count"] == 2
    actions = {d["action"] for d in out["dispositions"]}
    assert actions == {"queue_pa_review", "propose_intervention"}


def test_pa_queue_rejects_wrong_scope() -> None:
    store = _store()
    with pytest.raises(AuthError):
        gw_tools.pa_queue(store=store, token=TOKEN, scope="quality", caller_id="x")


# ---------------------------------------------------------------------------
# panel_overview
# ---------------------------------------------------------------------------


def test_panel_overview_returns_pcp_panel_redacted() -> None:
    store = _store()
    store.save_member(_make_member("M1", pcp="DR-1"))
    store.save_member(_make_member("M2", pcp="DR-1"))
    store.save_member(_make_member("M3", pcp="DR-2"))

    out = gw_tools.panel_overview(
        "DR-1",
        store=store,
        token=TOKEN,
        scope="care_manager",
        caller_id="cm-1",
    )

    assert out["count"] == 2
    member_ids = {m["member_id"] for m in out["members"]}
    assert member_ids == {"M1", "M2"}
    # PHI redaction still applies to head records.
    assert all(m["dob_year"] == gw_tools.REDACTED for m in out["members"])
    assert all(m["zip3"] == gw_tools.REDACTED for m in out["members"])


# ---------------------------------------------------------------------------
# cohort_overview
# ---------------------------------------------------------------------------


def test_cohort_overview_aggregates_distinct_members() -> None:
    store = _store()
    # Two scores for M1 in the same dimension should count as one member.
    store.save_risk_score(_make_score("M1", RiskDimension.READMISSION, 0.7))
    store.save_risk_score(_make_score("M1", RiskDimension.READMISSION, 0.8))
    store.save_risk_score(_make_score("M2", RiskDimension.READMISSION, 0.6))
    store.save_risk_score(_make_score("M3", RiskDimension.CARE_GAP, 0.55))
    store.save_risk_score(_make_score("M4", RiskDimension.CARE_GAP, 0.2))  # below cutoff

    out = gw_tools.cohort_overview(
        store=store, token=TOKEN, scope="quality", caller_id="q-1",
    )

    rows = {row["dimension"]: row["members"] for row in out["rows"]}
    assert rows.get("readmission") == 2  # M1 + M2
    assert rows.get("care_gap") == 1  # only M3 above 0.5


# ---------------------------------------------------------------------------
# related_entities
# ---------------------------------------------------------------------------


def test_related_entities_distills_event_buckets() -> None:
    store = _store()
    for i, (family, kind, src) in enumerate(
        [
            ("ENCOUNTER", "office_visit", "claims"),
            ("PHARMACY", "rx_filled", "pbm"),
            ("PHARMACY", "rx_filled", "pbm"),  # duplicate kind
            ("LAB", "lab_resulted", "lab_vendor_a"),
        ],
    ):
        store.save_event(
            {
                "event_id": f"E{i}",
                "member_id": "M1",
                "family": family,
                "kind": kind,
                "ts": "2025-01-01T00:00:00+00:00",
                "source_system": src,
                "attributes": {},
            },
        )

    out = gw_tools.related_entities(
        "M1", store=store, token=TOKEN, scope="care_manager", caller_id="cm-1",
    )

    assert out["event_count"] == 4
    assert out["families"] == ["ENCOUNTER", "LAB", "PHARMACY"]
    assert out["kinds"] == ["lab_resulted", "office_visit", "rx_filled"]
    assert out["source_systems"] == ["claims", "lab_vendor_a", "pbm"]
