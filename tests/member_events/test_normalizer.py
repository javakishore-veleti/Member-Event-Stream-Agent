"""Tests for the pure normalize() function."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from member_event_stream_agent.member_events.normalizer import normalize
from member_event_stream_agent.member_events.schemas import EventFamily, RawEvent


def _raw(**overrides: object) -> RawEvent:
    base: dict[str, object] = {
        "event_id": "E-1",
        "member_id": "M-1",
        "family": "ENCOUNTER",
        "kind": "OFFICE_VISIT",
        "ts": datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
        "source_system": "adt",
        "attributes": {"PrimaryDx": "I10"},
    }
    base.update(overrides)
    return RawEvent(**base)


def test_normalize_lowercases_kind_and_attribute_keys() -> None:
    event = normalize(_raw())
    assert event is not None
    assert event.kind == "office_visit"
    assert "primarydx" in event.attributes
    assert "PrimaryDx" not in event.attributes


def test_normalize_validates_family_into_enum() -> None:
    event = normalize(_raw(family="claim"))
    assert event is not None
    assert event.family == EventFamily.CLAIM


def test_normalize_rejects_unknown_family() -> None:
    with pytest.raises(ValueError, match="unknown event family"):
        normalize(_raw(family="not-a-family"))


def test_normalize_drops_noise_events() -> None:
    assert normalize(_raw(kind="HEARTBEAT")) is None
    assert normalize(_raw(kind="diagnostic_ping")) is None


def test_payload_hash_is_deterministic() -> None:
    a = normalize(_raw())
    b = normalize(_raw())
    assert a is not None and b is not None
    assert a.payload_hash == b.payload_hash


def test_payload_hash_changes_when_content_changes() -> None:
    a = normalize(_raw())
    b = normalize(_raw(attributes={"PrimaryDx": "E11.9"}))
    assert a is not None and b is not None
    assert a.payload_hash != b.payload_hash
