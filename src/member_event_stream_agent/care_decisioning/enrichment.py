"""EnrichmentAgent — load the longitudinal Member 360 context onto ctx.

Pulls the Member record and the most recent events from member_record
(MongoStore). The Scoring stage will reason over what is attached here.

This stage is the only place in the pipeline that touches storage on the
read path. Keeping the read centralized means caching, prefetching, or
swapping member_record for a different backend later only requires changes
in one place.
"""
from __future__ import annotations

from member_event_stream_agent.member_record.mongo import MongoStore

from .base import Agent, PipelineCtx


class EnrichmentAgent:
    name: str = "enrichment"

    def __init__(self, store: MongoStore, recent_events_limit: int = 20) -> None:
        self._store = store
        self._limit = recent_events_limit

    async def run(self, ctx: PipelineCtx) -> PipelineCtx:
        if ctx.skip:
            ctx.trace(self.name, skipped=True)
            return ctx

        ctx.member = self._store.get_member(ctx.event.member_id)
        ctx.recent_events = self._store.get_recent_events(
            ctx.event.member_id,
            limit=self._limit,
        )
        ctx.trace(
            self.name,
            member_found=ctx.member is not None,
            recent_events_count=len(ctx.recent_events),
        )
        return ctx
