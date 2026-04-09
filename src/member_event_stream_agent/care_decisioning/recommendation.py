"""RecommendationAgent — map a RiskScore to a Disposition.

The mapping is intentionally explicit per use case: a high readmission
score notifies a care manager, a high care_gap score opens an outreach,
a PA decision always queues for review (unless a future LLM-backed
ScoringAgent decides otherwise), and so on. Thresholds live in code for
Block 4 and will move to MongoDB-backed configurable rules later.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from member_event_stream_agent.member_record.schemas import (
    Disposition,
    DispositionAction,
    RiskDimension,
)

from .base import Agent, PipelineCtx


class RecommendationAgent:
    name: str = "recommendation"

    async def run(self, ctx: PipelineCtx) -> PipelineCtx:
        if ctx.skip or ctx.risk_score is None or ctx.use_case is None:
            ctx.trace(self.name, skipped=True)
            return ctx

        action = self._action_for(ctx.use_case, ctx.risk_score.score)

        ctx.disposition = Disposition(
            payer_org_id=ctx.payer_org_id,
            disposition_id=str(uuid.uuid4()),
            member_id=ctx.event.member_id,
            risk_score_id=ctx.risk_score.risk_score_id,
            action=action,
            produced_at=datetime.now(tz=timezone.utc),
        )
        ctx.trace(self.name, action=action.value, score=ctx.risk_score.score)
        return ctx

    def _action_for(
        self,
        use_case: RiskDimension,
        score: float,
    ) -> DispositionAction:
        if use_case == RiskDimension.READMISSION:
            return (
                DispositionAction.NOTIFY_CARE_MANAGER
                if score >= 0.6
                else DispositionAction.NONE
            )
        if use_case == RiskDimension.POLYPHARMACY:
            return (
                DispositionAction.PROPOSE_INTERVENTION
                if score >= 0.7
                else (
                    DispositionAction.NOTIFY_CARE_MANAGER
                    if score >= 0.5
                    else DispositionAction.NONE
                )
            )
        if use_case == RiskDimension.CARE_GAP:
            return (
                DispositionAction.OPEN_OUTREACH
                if score >= 0.4
                else DispositionAction.NONE
            )
        if use_case == RiskDimension.PA_DECISION:
            return DispositionAction.QUEUE_PA_REVIEW
        if use_case == RiskDimension.FWA:
            return (
                DispositionAction.ESCALATE_FWA
                if score >= 0.6
                else DispositionAction.NONE
            )
        if use_case == RiskDimension.ADHERENCE:
            return (
                DispositionAction.NOTIFY_CARE_MANAGER
                if score >= 0.5
                else DispositionAction.NONE
            )
        return DispositionAction.NONE
