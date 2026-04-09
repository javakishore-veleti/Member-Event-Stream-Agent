from datetime import date

import mongomock
from fastapi.testclient import TestClient

from member_event_stream_agent.main import app
from member_event_stream_agent.member_record.mongo import MongoStore
from member_event_stream_agent.member_record.schemas import LineOfBusiness, Member
from member_event_stream_agent.payer_api.app import create_app

client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version() -> None:
    response = client.get("/version")
    assert response.status_code == 200
    assert "version" in response.json()


def _seeded_app() -> TestClient:
    store = MongoStore(mongomock.MongoClient(), "mesa_test", "test-payer")
    store.save_member(
        Member(
            payer_org_id="test-payer",
            member_id="M42",
            plan_id="P1",
            line_of_business=LineOfBusiness.COMMERCIAL,
            eligibility_start=date(2024, 1, 1),
            dob_year=1980,
            zip3="021",
        ),
    )
    return TestClient(create_app(store=store))


def test_get_member_round_trip() -> None:
    api = _seeded_app()
    resp = api.get("/members/M42")
    assert resp.status_code == 200
    assert resp.json()["member_id"] == "M42"


def test_get_member_404() -> None:
    api = _seeded_app()
    assert api.get("/members/missing").status_code == 404
