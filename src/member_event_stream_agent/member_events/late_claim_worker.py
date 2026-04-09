"""LateClaimRescoreWorker — re-runs scoring when a late claim arrives.

A real claim file lands days or weeks after the service date. By the time
it arrives, any RiskScore the pipeline produced for that member from
encounter / pharmacy / lab events may be stale because it was missing this
claim's evidence. This worker subscribes to the same MemberEvent stream as
the main pipeline worker; whenever it sees a CLAIM event it triggers a
rescore for every dimension the member already has a score in.

The worker is additive: callers can run it alongside the main Pipeline
worker (both consume the same stream) without changing the pipeline path.
The main pipeline still runs Triage on the claim itself (which routes to
the FWA dimension); this worker covers the *other* dimensions whose
historical scores need refreshing in light of the new evidence.
"""
from __future__ import annotations

import asyncio

import structlog

from ..care_decisioning.rescore import Rescorer
from ..member_record.mongo import MongoStore
from ..member_record.schemas import RiskDimension
from .schemas import EventFamily, MemberEvent

# We deliberately skip FWA in the rescore loop because the main Pipeline
# already routes CLAIM/claim_received to FWA via Triage — re-running it
# from this worker would double-write.
_RESCORE_DIMENSIONS_SKIP: frozenset[RiskDimension] = frozenset({RiskDimension.FWA})


class LateClaimRescoreWorker:
    def __init__(
        self,
        store: MongoStore,
        rescorer: Rescorer,
    ) -> None:
        self._store = store
        self._rescorer = rescorer
        self._log = structlog.get_logger(__name__)

    async def handle(self, event: MemberEvent) -> list[RiskDimension]:
        """Process one event. Returns the dimensions actually rescored."""
        if event.family != EventFamily.CLAIM:
            return []

        existing = self._store.get_member_risk_dimensions(event.member_id)
        rescored: list[RiskDimension] = []
        for raw in existing:
            try:
                dim = RiskDimension(raw)
            except ValueError:
                continue
            if dim in _RESCORE_DIMENSIONS_SKIP:
                continue
            await self._rescorer.rescore(
                event.member_id, dim, trigger_event_id=event.event_id,
            )
            rescored.append(dim)

        if rescored:
            self._log.info(
                "late_claim.rescored",
                member_id=event.member_id,
                event_id=event.event_id,
                dimensions=[d.value for d in rescored],
            )
        return rescored

    async def run(self, stream: "asyncio.Queue[MemberEvent]") -> None:
        """Drain a queue of events. Used by main.py to spawn the loop."""
        try:
            while True:
                event = await stream.get()
                await self.handle(event)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            pass
