"""Smoke tests for the event-stream Pydantic models."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from member_event_stream_agent.member_events.schemas import (
    EventFamily,
    MemberEvent,
    RawEvent,
)


def test_raw_event_accepts_extra_fields() -> None:
    raw = RawEvent.model_validate(
        {
            "event_id": "E-1",
            "member_id": "M-1",
            "family": "encounter",
            "kind": "OFFICE_VISIT",
            "ts": "2026-04-08T12:00:00+00:00",
            "source_system": "adt",
            "attributes": {"primary_dx_codes": ["I10"]},
            "vendor_specific_extra": "ok",
        },
    )
    assert raw.family == "encounter"
    assert raw.kind == "OFFICE_VISIT"


def test_member_event_is_immutable() -> None:
    event = MemberEvent(
        event_id="E-1",
        member_id="M-1",
        family=EventFamily.ENCOUNTER,
        kind="office_visit",
        ts=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
        source_system="adt",
        attributes={},
        payload_hash="abc",
        received_at=datetime(2026, 4, 8, 12, 0, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(ValidationError):
        event.kind = "edit_attempt"  # type: ignore[misc]


def test_member_event_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        MemberEvent.model_validate(
            {
                "event_id": "E-1",
                "member_id": "M-1",
                "family": "ENCOUNTER",
                "kind": "office_visit",
                "ts": "2026-04-08T12:00:00+00:00",
                "source_system": "adt",
                "attributes": {},
                "payload_hash": "abc",
                "received_at": "2026-04-08T12:00:01+00:00",
                "rogue": "extra",
            },
        )
