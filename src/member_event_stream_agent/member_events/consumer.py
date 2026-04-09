"""Async event consumer with two backends.

Real backend  — aiokafka.AIOKafkaConsumer (selected when KAFKA_BROKERS is a
                normal broker list like "localhost:9092").
Synthetic     — drains the InMemoryBus from member_events.producer. Selected
                when KAFKA_BROKERS starts with "memory://".

Iteration model:
    consumer = EventConsumer(brokers, topic)
    async for member_event in consumer.iter_events():
        ...                                  # MemberEvent already normalized
        if some_condition:
            await consumer.stop()
            break

The consumer drops noise events (whatever normalize() returns None for) so
caller code never has to filter them out.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, TYPE_CHECKING

from .normalizer import normalize
from .producer import DEFAULT_BUS, InMemoryBus
from .schemas import MemberEvent, RawEvent

if TYPE_CHECKING:
    from aiokafka import AIOKafkaConsumer


class EventConsumer:
    def __init__(
        self,
        brokers: str,
        topic: str,
        group_id: str = "mesa-default",
        *,
        bus: InMemoryBus | None = None,
        synthetic_poll_seconds: float = 0.05,
    ) -> None:
        self._brokers = brokers
        self._topic = topic
        self._group_id = group_id
        self._bus = bus
        self._poll = synthetic_poll_seconds
        self._stopped = False

    @property
    def is_synthetic(self) -> bool:
        return self._brokers.startswith("memory://")

    async def stop(self) -> None:
        self._stopped = True

    async def iter_events(self) -> AsyncIterator[MemberEvent]:
        backend = self._synthetic_backend() if self.is_synthetic else self._kafka_backend()
        async for raw in backend:
            event = normalize(raw)
            if event is not None:
                yield event

    # ------------------------------------------------------------------

    async def _synthetic_backend(self) -> AsyncIterator[RawEvent]:
        bus = self._bus or DEFAULT_BUS
        while not self._stopped:
            try:
                raw = await asyncio.wait_for(bus.consume(), timeout=self._poll)
                yield raw
            except asyncio.TimeoutError:
                continue

    async def _kafka_backend(self) -> AsyncIterator[RawEvent]:
        import json

        from aiokafka import AIOKafkaConsumer  # local import keeps tests dep-light

        consumer = AIOKafkaConsumer(
            self._topic,
            bootstrap_servers=self._brokers,
            group_id=self._group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        )
        await consumer.start()
        try:
            async for msg in consumer:
                if self._stopped:
                    break
                yield RawEvent.model_validate(msg.value)
        finally:
            await consumer.stop()
