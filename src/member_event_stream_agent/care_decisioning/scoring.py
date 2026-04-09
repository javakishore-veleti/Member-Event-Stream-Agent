"""ScoringAgent — deterministic rule-based scorer (the fall-back twin).

Each use case has its own private heuristic that operates over ctx.event
and ctx.recent_events and returns (score, rationale, cited_event_ids).

This agent is now the *fall-back* path: AdkScoringAgent (in
care_decisioning/adk/scoring_adk.py) is the production-preferred stage
when LLM_PROVIDER=google_adk. The rules below still run when the LLM is
unreachable, when LLM_PROVIDER=stub, or for any deployment that wants a
fully deterministic scoring path.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from member_event_stream_agent.member_record.schemas import (
    RiskDimension,
    RiskScore,
)

from .base import Agent, PipelineCtx


class ScoringAgent:
    name: str = "scoring"
    model_version: str = "v0.0.1-rules"
    default_confidence: float = 0.5

    async def run(self, ctx: PipelineCtx) -> PipelineCtx:
        if ctx.skip or ctx.use_case is None:
            ctx.trace(self.name, skipped=True)
            return ctx

        score, rationale, citations = self._score(ctx)

        ctx.risk_score = RiskScore(
            payer_org_id=ctx.payer_org_id,
            risk_score_id=str(uuid.uuid4()),
            member_id=ctx.event.member_id,
            dimension=ctx.use_case,
            score=score,
            confidence=self.default_confidence,
            rationale=rationale,
            citations=citations,
            model_version=self.model_version,
            produced_at=datetime.now(tz=timezone.utc),
        )
        ctx.trace(
            self.name,
            dimension=ctx.use_case.value,
            score=score,
            rationale=rationale,
            citation_count=len(citations),
        )
        return ctx

    # ------------------------------------------------------------------
    # Private heuristics — one per supported use case
    # ------------------------------------------------------------------

    def _score(self, ctx: PipelineCtx) -> tuple[float, str, list[str]]:
        dispatch = {
            RiskDimension.READMISSION: self._score_readmission,
            RiskDimension.POLYPHARMACY: self._score_polypharmacy,
            RiskDimension.CARE_GAP: self._score_care_gap,
            RiskDimension.PA_DECISION: self._score_pa_decision,
            RiskDimension.FWA: self._score_fwa,
            RiskDimension.ADHERENCE: self._score_adherence,
        }
        scorer = dispatch.get(ctx.use_case) if ctx.use_case else None
        if scorer is None:
            return 0.1, "no scorer for this use case", [ctx.event.event_id]
        return scorer(ctx)

    def _score_readmission(self, ctx: PipelineCtx) -> tuple[float, str, list[str]]:
        prior_admits = [
            e
            for e in ctx.recent_events
            if e.get("family") == "ENCOUNTER" and e.get("kind") == "inpatient_admit"
        ]
        score = min(0.3 + 0.2 * len(prior_admits), 0.95)
        rationale = (
            f"{len(prior_admits)} prior inpatient admit(s) in recent history; "
            f"current event = {ctx.event.kind}"
        )
        citations = [e["event_id"] for e in prior_admits[:3] if "event_id" in e]
        citations.append(ctx.event.event_id)
        return score, rationale, citations

    def _score_polypharmacy(self, ctx: PipelineCtx) -> tuple[float, str, list[str]]:
        active_fills = [
            e
            for e in ctx.recent_events
            if e.get("family") == "PHARMACY" and e.get("kind") == "rx_filled"
        ]
        score = min(0.1 + 0.12 * len(active_fills), 0.95)
        rationale = f"{len(active_fills)} recent rx_filled event(s) in window"
        citations = [e["event_id"] for e in active_fills[:5] if "event_id" in e]
        citations.append(ctx.event.event_id)
        return score, rationale, citations

    def _score_care_gap(self, ctx: PipelineCtx) -> tuple[float, str, list[str]]:
        # Baseline: assume the gap is open until prior closure evidence is found.
        return 0.4, "baseline care gap evaluation; no closure evidence", [
            ctx.event.event_id,
        ]

    def _score_pa_decision(self, ctx: PipelineCtx) -> tuple[float, str, list[str]]:
        return 0.5, "baseline PA triage; pend for clinical review", [ctx.event.event_id]

    def _score_fwa(self, ctx: PipelineCtx) -> tuple[float, str, list[str]]:
        return 0.2, "single-event FWA stub; cluster scoring lands later", [
            ctx.event.event_id,
        ]

    def _score_adherence(self, ctx: PipelineCtx) -> tuple[float, str, list[str]]:
        return 0.3, "adherence stub; PDC computation lands later", [ctx.event.event_id]
