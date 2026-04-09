"""Synthetic event seeder for the in-memory Kafka stand-in.

When the process runs against KAFKA_BROKERS=memory://, the EventConsumer
drains DEFAULT_BUS but nothing publishes to it. This module fills that gap
for local dev and the end-to-end smoke test required by DoD #4: it seeds
one fake Member into the Member 360 store so EnrichmentAgent has something
to attach, then loops publishing fake RawEvents whose (family, kind) pairs
hit Triage rules so the pipeline produces RiskScores and CaseFiles.

Real-Kafka runs do not import this module — main.py only spawns the seeder
when the synthetic backend is selected.
"""
from __future__ import annotations

import asyncio
import itertools
import uuid
from datetime import date, datetime, timezone

from ..member_record.mongo import MongoStore
from ..member_record.schemas import LineOfBusiness, Member
from .producer import DEFAULT_BUS, InMemoryBus
from .schemas import RawEvent

# (family, kind) tuples that hit a real Triage rule -> emit a RiskScore.
_EVENT_CYCLE: tuple[tuple[str, str], ...] = (
    ("ENCOUNTER", "office_visit"),
    ("PHARMACY", "rx_filled"),
    ("ENCOUNTER", "inpatient_discharge"),
    ("LAB", "lab_resulted"),
)


def seed_demo_member(store: MongoStore, member_id: str = "DEMO-1") -> None:
    """Idempotently insert one demo Member so EnrichmentAgent has a hit."""
    if store.get_member(member_id) is not None:
        return
    store.save_member(
        Member(
            payer_org_id=store.payer_org_id,
            member_id=member_id,
            plan_id="DEMO-PLAN",
            line_of_business=LineOfBusiness.COMMERCIAL,
            eligibility_start=date(2024, 1, 1),
            dob_year=1980,
            zip3="021",
        ),
    )


async def run_seeder(
    *,
    interval_seconds: float = 1.0,
    bus: InMemoryBus | None = None,
    member_id: str = "DEMO-1",
    source_system: str = "synthetic",
) -> None:
    """Publish one synthetic RawEvent to the bus every `interval_seconds`.

    Cancellation-safe: callers (lifespan handler, tests) cancel the task on
    shutdown and the loop unwinds cleanly.
    """
    target = bus or DEFAULT_BUS
    for family, kind in itertools.cycle(_EVENT_CYCLE):
        raw = RawEvent(
            event_id=str(uuid.uuid4()),
            member_id=member_id,
            family=family,
            kind=kind,
            ts=datetime.now(tz=timezone.utc),
            source_system=source_system,
            attributes={},
        )
        await target.publish(raw)
        await asyncio.sleep(interval_seconds)
