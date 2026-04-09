"""ADK-backed RecommendationAgent.

The rule-based twin is a static threshold ladder per RiskDimension. The
ADK variant asks the LLM to pick a DispositionAction given the score, the
use case, and the narrative AdkEnrichmentAgent attached, then coerces the
response into the DispositionAction enum. Anything outside the enum (or
any LLM error) drops back to the deterministic ladder so the pipeline
always emits a Disposition.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog

from ...member_record.schemas import Disposition, DispositionAction
from ..base import PipelineCtx
from ..recommendation import RecommendationAgent
from .llm import LlmClient, RecommendationResponse

_PROMPT = (
    "You are a healthcare care-team routing assistant. Given a risk score,\n"
    "the use case it scored, and a short member narrative, choose exactly\n"
    "one action from this set: none, notify_care_manager, open_outreach,\n"
    "queue_pa_review, propose_intervention, escalate_fwa, draft_pa_response.\n"
    "Return strict JSON with keys action and notes."
)


def _coerce_action(raw: str) -> DispositionAction | None:
    try:
        return DispositionAction(raw.strip().lower())
    except ValueError:
        return None


class AdkRecommendationAgent:
    name: str = "recommendation_adk"

    def __init__(
        self,
        client: LlmClient,
        *,
        fallback: RecommendationAgent | None = None,
    ) -> None:
        self._client = client
        self._fallback = fallback or RecommendationAgent()
        self._log = structlog.get_logger(__name__)

    async def run(self, ctx: PipelineCtx) -> PipelineCtx:
        if ctx.skip or ctx.risk_score is None or ctx.use_case is None:
            ctx.trace(self.name, skipped=True)
            return ctx

        try:
            response: RecommendationResponse = await self._client.complete_recommendation(
                prompt=_PROMPT,
                context={
                    "use_case": ctx.use_case.value,
                    "score": ctx.risk_score.score,
                    "rationale": ctx.risk_score.rationale,
                    "narrative": ctx.narrative,
                },
            )
        except Exception as exc:  # noqa: BLE001 — intentional broad fall-back
            self._log.warning("recommendation_adk.fallback", error=str(exc))
            ctx.trace(self.name, fallback=True, error=str(exc))
            return await self._fallback.run(ctx)

        action = _coerce_action(response.action)
        if action is None:
            self._log.warning("recommendation_adk.unknown_action", raw=response.action)
            ctx.trace(self.name, fallback=True, reason="unknown_action", raw=response.action)
            return await self._fallback.run(ctx)

        ctx.disposition = Disposition(
            payer_org_id=ctx.payer_org_id,
            disposition_id=str(uuid.uuid4()),
            member_id=ctx.event.member_id,
            risk_score_id=ctx.risk_score.risk_score_id,
            action=action,
            notes=response.notes or None,
            produced_at=datetime.now(tz=timezone.utc),
        )
        ctx.trace(
            self.name,
            source="adk",
            action=action.value,
            score=ctx.risk_score.score,
        )
        return ctx
