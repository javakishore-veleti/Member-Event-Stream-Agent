"""Pure normalization from RawEvent to MemberEvent.

Responsibilities:
    1. Drop noise events (heartbeats, diagnostic pings).
    2. Coerce family to the EventFamily enum (rejects unknown families).
    3. Lowercase kind and attribute keys for consistent downstream matching.
    4. Compute a deterministic payload_hash so dedup at the storage layer
       (member_record.MongoStore.save_event) is reliable across replays.
    5. Stamp received_at with the wall-clock time of normalization.

This module imports nothing from infrastructure (no Kafka, no Mongo).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .schemas import EventFamily, MemberEvent, RawEvent

NOISE_KINDS: frozenset[str] = frozenset(
    {
        "heartbeat",
        "diagnostic_ping",
        "noop",
        "_internal_keepalive",
    },
)


def normalize(raw: RawEvent) -> MemberEvent | None:
    """Normalize a RawEvent into a MemberEvent.

    Returns None when the event is noise (caller should drop it). Raises
    ValueError when the family is not a valid EventFamily.
    """
    kind = raw.kind.strip().lower()
    if kind in NOISE_KINDS:
        return None

    try:
        family = EventFamily(raw.family.strip().upper())
    except ValueError as exc:
        raise ValueError(f"unknown event family: {raw.family!r}") from exc

    attributes = {str(k).lower(): v for k, v in (raw.attributes or {}).items()}

    canonical_payload = {
        "event_id": raw.event_id,
        "member_id": raw.member_id,
        "family": family.value,
        "kind": kind,
        "ts": raw.ts.isoformat(),
        "source_system": raw.source_system,
        "attributes": attributes,
    }
    payload_hash = hashlib.sha256(
        json.dumps(canonical_payload, sort_keys=True, default=str).encode("utf-8"),
    ).hexdigest()

    return MemberEvent(
        event_id=raw.event_id,
        member_id=raw.member_id,
        family=family,
        kind=kind,
        ts=raw.ts,
        source_system=raw.source_system,
        attributes=attributes,
        payload_hash=payload_hash,
        received_at=datetime.now(tz=timezone.utc),
    )
