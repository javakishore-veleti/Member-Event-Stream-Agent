from fastapi.testclient import TestClient

from member_event_stream_agent.main import app

client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version() -> None:
    response = client.get("/version")
    assert response.status_code == 200
    assert "version" in response.json()
