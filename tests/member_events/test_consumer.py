"""Round-trip tests for the synthetic consumer/producer pair."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from member_event_stream_agent.member_events.consumer import EventConsumer
from member_event_stream_agent.member_events.producer import EventProducer, InMemoryBus
from member_event_stream_agent.member_events.schemas import RawEvent


def _raw(event_id: str = "E-1", kind: str = "OFFICE_VISIT") -> RawEvent:
    return RawEvent(
        event_id=event_id,
        member_id="M-1",
        family="ENCOUNTER",
        kind=kind,
        ts=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
        source_system="adt",
        attributes={"PrimaryDx": "I10"},
    )


@pytest.mark.asyncio
async def test_synthetic_round_trip_yields_normalized_event() -> None:
    bus = InMemoryBus()
    producer = EventProducer(brokers="memory://", topic="t", bus=bus)
    await producer.start()

    await producer.publish(_raw())

    consumer = EventConsumer(brokers="memory://", topic="t", bus=bus)

    received = None
    async for event in consumer.iter_events():
        received = event
        await consumer.stop()
        break

    assert received is not None
    assert received.event_id == "E-1"
    assert received.kind == "office_visit"  # normalized
    assert received.family.value == "ENCOUNTER"
    assert "primarydx" in received.attributes
    assert received.payload_hash  # set


@pytest.mark.asyncio
async def test_consumer_skips_noise_events() -> None:
    bus = InMemoryBus()
    producer = EventProducer(brokers="memory://", topic="t", bus=bus)
    await producer.start()

    await producer.publish(_raw(event_id="E-noise", kind="HEARTBEAT"))
    await producer.publish(_raw(event_id="E-real"))

    consumer = EventConsumer(brokers="memory://", topic="t", bus=bus)

    received = None
    async for event in consumer.iter_events():
        received = event
        await consumer.stop()
        break

    assert received is not None
    assert received.event_id == "E-real"


@pytest.mark.asyncio
async def test_producer_synthetic_mode_does_not_require_kafka() -> None:
    bus = InMemoryBus()
    producer = EventProducer(brokers="memory://", topic="t", bus=bus)
    # start() must be a no-op for synthetic — no Kafka cluster required.
    await producer.start()
    assert producer.is_synthetic is True
