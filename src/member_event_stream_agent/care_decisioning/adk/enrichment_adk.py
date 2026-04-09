"""ADK-backed EnrichmentAgent.

Enrichment is mostly a database read — the LLM cannot invent rows that
do not exist in the Member 360 store. The value the LLM adds is a short
narrative summary of the recent timeline that downstream stages
(particularly scoring) can lean on instead of re-walking raw events. So
this agent runs the same DB read its rule-based twin does, then asks the
LLM for a one-paragraph narrative and attaches it to ctx.narrative.

Falls back to the rule-based EnrichmentAgent on LLM error: the DB reads
have already happened by then, so the fall-back is a no-op annotation.
"""
from __future__ import annotations

import structlog

from ...member_record.mongo import MongoStore
from ..base import PipelineCtx
from ..enrichment import EnrichmentAgent
from .llm import LlmClient, NarrativeResponse

_PROMPT = (
    "You are a healthcare summarization assistant. Given a member's recent\n"
    "event timeline, write a single short paragraph summarizing the most\n"
    "clinically relevant signals (admits, ED visits, fills, abnormal labs).\n"
    "Do not invent events. Return JSON with one key: narrative."
)


class AdkEnrichmentAgent:
    name: str = "enrichment_adk"

    def __init__(
        self,
        store: MongoStore,
        client: LlmClient,
        *,
        recent_events_limit: int = 20,
    ) -> None:
        self._inner = EnrichmentAgent(store, recent_events_limit=recent_events_limit)
        self._client = client
        self._log = structlog.get_logger(__name__)

    async def run(self, ctx: PipelineCtx) -> PipelineCtx:
        # Always do the DB read first — the LLM never replaces it.
        ctx = await self._inner.run(ctx)
        if ctx.skip:
            return ctx

        try:
            response: NarrativeResponse = await self._client.complete_narrative(
                prompt=_PROMPT,
                context={
                    "member_id": ctx.event.member_id,
                    "recent_events": [
                        {
                            "family": e.get("family"),
                            "kind": e.get("kind"),
                            "ts": e.get("ts"),
                        }
                        for e in ctx.recent_events[:20]
                    ],
                },
            )
            ctx.narrative = response.narrative
            ctx.trace(self.name, source="adk", narrative_chars=len(response.narrative))
        except Exception as exc:  # noqa: BLE001 — narrative is best-effort
            self._log.warning("enrichment_adk.fallback", error=str(exc))
            ctx.trace(self.name, fallback=True, error=str(exc))
        return ctx
