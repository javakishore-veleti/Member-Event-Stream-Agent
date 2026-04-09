"""Tests for the structlog PHI-redaction processor in logging.py.

The processor must:
    1. Redact baseline PHI keys (ssn, dob, email, phone, mrn, ...) at any
       depth.
    2. Honor json_schema_extra={"phi": True} on the member_record schemas
       so adding a new PHI field automatically redacts it in logs.
    3. Walk nested dicts and lists.
    4. Pass non-PHI fields through untouched.
    5. Never raise — even on exotic event payloads.
"""
from __future__ import annotations

from member_event_stream_agent.logging import (
    PHI_KEYS,
    REDACTED,
    redact_phi,
)


def _redact(event: dict) -> dict:
    return redact_phi(None, "info", event)


def test_phi_keys_include_schema_tagged_fields() -> None:
    # Member.dob_year and Member.zip3 are tagged phi=True in the schemas.
    assert "dob_year" in PHI_KEYS
    assert "zip3" in PHI_KEYS


def test_phi_keys_include_baseline() -> None:
    for k in ("ssn", "dob", "email", "phone", "mrn"):
        assert k in PHI_KEYS


def test_top_level_phi_redacted() -> None:
    out = _redact(
        {"event": "lookup", "member_id": "M1", "ssn": "123-45-6789", "email": "x@y.com"},
    )
    assert out["ssn"] == REDACTED
    assert out["email"] == REDACTED
    assert out["member_id"] == "M1"
    assert out["event"] == "lookup"


def test_nested_phi_redacted() -> None:
    out = _redact(
        {
            "event": "trace",
            "member": {
                "member_id": "M1",
                "dob_year": 1980,
                "zip3": "021",
                "plan_id": "P1",
            },
        },
    )
    assert out["member"]["dob_year"] == REDACTED
    assert out["member"]["zip3"] == REDACTED
    assert out["member"]["plan_id"] == "P1"
    assert out["member"]["member_id"] == "M1"


def test_list_of_dicts_redacted() -> None:
    out = _redact(
        {
            "event": "panel",
            "members": [
                {"member_id": "M1", "dob_year": 1980},
                {"member_id": "M2", "dob_year": 1990, "email": "z@y.com"},
            ],
        },
    )
    assert out["members"][0]["dob_year"] == REDACTED
    assert out["members"][1]["dob_year"] == REDACTED
    assert out["members"][1]["email"] == REDACTED
    assert out["members"][0]["member_id"] == "M1"


def test_case_insensitive_keys() -> None:
    out = _redact({"SSN": "123-45-6789", "Email": "a@b.com"})
    assert out["SSN"] == REDACTED
    assert out["Email"] == REDACTED


def test_non_phi_passes_through() -> None:
    out = _redact({"event": "ok", "score": 0.42, "citations": ["E1", "E2"]})
    assert out == {"event": "ok", "score": 0.42, "citations": ["E1", "E2"]}


def test_processor_never_raises_on_weird_input() -> None:
    class Weird:
        pass

    out = _redact({"event": "weird", "thing": Weird(), "ssn": "x"})
    assert out["ssn"] == REDACTED  # PHI still redacted
    assert isinstance(out["thing"], Weird)  # unknown type passed through
