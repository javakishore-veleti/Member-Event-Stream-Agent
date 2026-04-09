"""ADK-backed ScoringAgent.

Wraps an LlmClient and produces a RiskScore for the use case Triage
selected. The prompt grounds the LLM in the inbound MemberEvent + the
last N normalized events from member_record so the model has real
patient context to reason over instead of guessing.

Fall-back behavior: if the LlmClient raises (network, parse error,
guardrail violation), the agent silently falls back to the deterministic
rule-based ScoringAgent so the pipeline always produces a RiskScore.
The fall-back is recorded in the ctx.audit_trace so a reviewer can see
which decisions were LLM-backed and which were rule-based.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog

from ...member_record.schemas import RiskScore
from ..base import PipelineCtx
from ..scoring import ScoringAgent
from .llm import LlmClient, ScoringResponse


_PROMPT = (
    "You are a healthcare risk-scoring assistant for a US health-plan payer.\n"
    "Given one inbound member event and the recent event history, return a\n"
    "score in [0, 1] for the named risk dimension, a one-sentence rationale,\n"
    "and a list of cited event_ids that drove the score. Do not invent events."
)


class AdkScoringAgent:
    name: str = "scoring_adk"
    model_version: str = "v0.1.0-adk"
    default_confidence: float = 0.7

    def __init__(
        self,
        client: LlmClient,
        *,
        fallback: ScoringAgent | None = None,
    ) -> None:
        self._client = client
        self._fallback = fallback or ScoringAgent()
        self._log = structlog.get_logger(__name__)

    async def run(self, ctx: PipelineCtx) -> PipelineCtx:
        if ctx.skip or ctx.use_case is None:
            ctx.trace(self.name, skipped=True)
            return ctx

        context = self._build_context(ctx)
        try:
            response: ScoringResponse = await self._client.complete_scoring(
                prompt=_PROMPT,
                context=context,
            )
            source = "adk"
        except Exception as exc:  # noqa: BLE001 — intentional broad fall-back
            self._log.warning("scoring_adk.fallback", error=str(exc))
            ctx.trace(self.name, fallback=True, error=str(exc))
            return await self._fallback.run(ctx)

        ctx.risk_score = RiskScore(
            payer_org_id=ctx.payer_org_id,
            risk_score_id=str(uuid.uuid4()),
            member_id=ctx.event.member_id,
            dimension=ctx.use_case,
            score=max(0.0, min(1.0, response.score)),
            confidence=self.default_confidence,
            rationale=response.rationale,
            citations=response.citations,
            model_version=self.model_version,
            produced_at=datetime.now(tz=timezone.utc),
        )
        ctx.trace(
            self.name,
            source=source,
            dimension=ctx.use_case.value,
            score=response.score,
            citation_count=len(response.citations),
        )
        return ctx

    def _build_context(self, ctx: PipelineCtx) -> dict[str, object]:
        return {
            "use_case": ctx.use_case.value if ctx.use_case else None,
            "event": {
                "event_id": ctx.event.event_id,
                "family": ctx.event.family.value,
                "kind": ctx.event.kind,
                "ts": ctx.event.ts.isoformat(),
            },
            "recent_events": [
                {
                    "event_id": e.get("event_id"),
                    "family": e.get("family"),
                    "kind": e.get("kind"),
                    "ts": e.get("ts"),
                }
                for e in ctx.recent_events[:20]
            ],
            "member_present": ctx.member is not None,
        }
