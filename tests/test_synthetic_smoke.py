"""End-to-end smoke for the synthetic worker path (DoD #4).

Wires a fresh MongoStore (mongomock), a Pipeline, an EventConsumer pointed
at a private InMemoryBus, and the synthetic seeder. Runs the seeder + worker
concurrently for a short window, then asserts at least one CaseFile and one
RiskScore landed in the store. Stays well under the 30s budget the dev plan
allots for the same end-to-end check.
"""
from __future__ import annotations

import asyncio

import mongomock
import pytest

from member_event_stream_agent.care_decisioning.pipeline import Pipeline
from member_event_stream_agent.member_events.consumer import EventConsumer
from member_event_stream_agent.member_events.producer import InMemoryBus
from member_event_stream_agent.member_events.synthetic_seeder import (
    run_seeder,
    seed_demo_member,
)
from member_event_stream_agent.member_record.mongo import MongoStore


async def _drain(consumer: EventConsumer, pipeline: Pipeline) -> None:
    async for event in consumer.iter_events():
        await pipeline.process(event)


@pytest.mark.asyncio
async def test_synthetic_seeder_produces_case_files() -> None:
    store = MongoStore(mongomock.MongoClient(), "mesa_smoke", "smoke-payer")
    seed_demo_member(store)
    pipeline = Pipeline(store)

    bus = InMemoryBus()
    consumer = EventConsumer("memory://", "member.events", bus=bus)

    seeder = asyncio.create_task(run_seeder(interval_seconds=0.01, bus=bus))
    worker = asyncio.create_task(_drain(consumer, pipeline))

    try:
        # Give the loop time to publish + process several events.
        for _ in range(50):
            await asyncio.sleep(0.05)
            if store._db["case_files"].count_documents({}) >= 1:
                break
    finally:
        await consumer.stop()
        for task in (seeder, worker):
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    assert store._db["case_files"].count_documents({}) >= 1
    assert store._db["risk_scores"].count_documents({}) >= 1
    assert store._db["events"].count_documents({}) >= 1
