"""Pydantic v2 schemas for the event-stream layer.

RawEvent  — what a source system actually emits. Loose-shaped, allows extra
            fields, family/kind not yet validated.
MemberEvent — the normalized envelope every other module in the codebase
              consumes (member_record persists it, care_decisioning scores
              over it). Strict-shaped and immutable.

EventFamily lives in member_record.schemas (it is also a persisted enum) and
is re-exported here for convenience so callers do not need to know which
package owns the canonical definition.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from member_event_stream_agent.member_record.schemas import EventFamily

__all__ = ["EventFamily", "RawEvent", "MemberEvent"]


class RawEvent(BaseModel):
    """Event exactly as it arrives on the wire from a source system."""

    model_config = ConfigDict(extra="allow")

    event_id: str
    member_id: str
    family: str  # uppercased and validated against EventFamily during normalize()
    kind: str  # lowercased during normalize()
    ts: datetime
    source_system: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class MemberEvent(BaseModel):
    """Normalized event envelope. Immutable. Carries provenance + dedup hash."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    member_id: str
    family: EventFamily
    kind: str
    ts: datetime
    source_system: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    payload_hash: str
    received_at: datetime
