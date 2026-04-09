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
from ..vector.base import VectorClient
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
        vector_client: VectorClient | None = None,
        vector_top_k: int = 5,
    ) -> None:
        self._inner = EnrichmentAgent(store, recent_events_limit=recent_events_limit)
        self._client = client
        self._vector_client = vector_client
        self._vector_top_k = vector_top_k
        self._log = structlog.get_logger(__name__)

    async def run(self, ctx: PipelineCtx) -> PipelineCtx:
        # Always do the DB read first — the LLM never replaces it.
        ctx = await self._inner.run(ctx)
        if ctx.skip:
            return ctx

        # Optional vector retrieval — best-effort, never blocks the pipeline.
        if self._vector_client is not None:
            try:
                hits = await self._vector_client.search_similar_contexts(
                    query_text=self._build_query_text(ctx),
                    member_id=ctx.event.member_id,
                    k=self._vector_top_k,
                )
                ctx.similar_contexts = [
                    {
                        "id": h.id,
                        "score": h.score,
                        "member_id": h.member_id,
                        "text": h.text,
                        "metadata": h.metadata,
                    }
                    for h in hits
                ]
                ctx.trace(self.name, vector_hits=len(hits), vector="ok")
            except Exception as exc:  # noqa: BLE001
                self._log.warning("enrichment_adk.vector_failed", error=str(exc))
                ctx.trace(self.name, vector="error", error=str(exc))

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

    def _build_query_text(self, ctx: PipelineCtx) -> str:
        """Compact text the vector backend can embed for similarity search."""
        recent = ", ".join(
            f"{e.get('family')}/{e.get('kind')}" for e in ctx.recent_events[:10]
        )
        return (
            f"member={ctx.event.member_id} "
            f"event={ctx.event.family.value}/{ctx.event.kind} "
            f"recent=[{recent}]"
        )
