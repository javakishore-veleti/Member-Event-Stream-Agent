"""Process entrypoint.

Builds the FastAPI app via the payer_api factory, wires the shared MongoStore
and care_decisioning Pipeline onto app.state, and — when the synthetic Kafka
backend is selected — spawns a background worker task on startup that drains
member events through the pipeline. Real Kafka is selected automatically when
KAFKA_BROKERS points at a normal broker list.

The MCP gateway server is built via care_team_gateway.server.build_mcp_server
so the same MongoStore instance backs both the HTTP and MCP surfaces. It is
constructed lazily because fastmcp is an optional runtime dep.
"""
from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI

from .care_decisioning.pipeline import Pipeline
from .config import get_settings
from .member_events.consumer import EventConsumer
from .payer_api.app import create_app

log = structlog.get_logger(__name__)


async def _run_worker(consumer: EventConsumer, pipeline: Pipeline) -> None:
    """Drain the event stream into the pipeline until the consumer stops."""
    try:
        async for event in consumer.iter_events():
            try:
                await pipeline.process(event)
            except Exception:  # pragma: no cover - defensive worker loop
                log.exception("worker.process_failed", event_id=event.event_id)
    except asyncio.CancelledError:  # pragma: no cover - shutdown path
        pass


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    consumer: EventConsumer | None = None
    task: asyncio.Task[None] | None = None
    if settings.kafka_brokers.startswith("memory://"):
        consumer = EventConsumer(settings.kafka_brokers, settings.kafka_topic)
        application.state.consumer = consumer
        task = asyncio.create_task(_run_worker(consumer, application.state.pipeline))
        application.state.worker_task = task
    try:
        yield
    finally:
        if consumer is not None:
            await consumer.stop()
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = create_app(lifespan=lifespan)
