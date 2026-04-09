"""Async event producer with two backends.

Real backend  — aiokafka.AIOKafkaProducer (selected when KAFKA_BROKERS is a
                normal broker list like "localhost:9092").
Synthetic     — an in-process asyncio.Queue (InMemoryBus). Selected when
                KAFKA_BROKERS starts with "memory://". Used for local dev
                without Docker and for offline tests.

Tests can construct their own InMemoryBus and inject it via the bus= keyword
to keep test cases isolated from each other.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .schemas import RawEvent

if TYPE_CHECKING:
    from aiokafka import AIOKafkaProducer


class InMemoryBus:
    """Asyncio queue acting as a Kafka stand-in for local dev and tests."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[RawEvent] = asyncio.Queue()

    async def publish(self, event: RawEvent) -> None:
        await self._queue.put(event)

    async def consume(self) -> RawEvent:
        return await self._queue.get()

    def qsize(self) -> int:
        return self._queue.qsize()


# Process-wide default bus used when no explicit bus= is passed.
DEFAULT_BUS = InMemoryBus()


class EventProducer:
    def __init__(
        self,
        brokers: str,
        topic: str,
        *,
        bus: InMemoryBus | None = None,
    ) -> None:
        self._brokers = brokers
        self._topic = topic
        self._bus = bus
        self._kafka: AIOKafkaProducer | None = None

    @property
    def is_synthetic(self) -> bool:
        return self._brokers.startswith("memory://")

    async def start(self) -> None:
        if self.is_synthetic:
            return
        from aiokafka import AIOKafkaProducer  # local import keeps tests dep-light

        import json

        self._kafka = AIOKafkaProducer(
            bootstrap_servers=self._brokers,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
        )
        await self._kafka.start()

    async def stop(self) -> None:
        if self._kafka is not None:
            await self._kafka.stop()
            self._kafka = None

    async def publish(self, event: RawEvent) -> None:
        if self.is_synthetic:
            bus = self._bus or DEFAULT_BUS
            await bus.publish(event)
            return
        if self._kafka is None:
            raise RuntimeError("EventProducer.start() must be awaited first")
        await self._kafka.send_and_wait(self._topic, event.model_dump(mode="json"))
