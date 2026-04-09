"""Rescorer — re-evaluate one (member, dimension) without going through Triage.

Late-arriving claims are a real production concern: a claim for a service
performed last week may not land in the payer until days or weeks later.
Any RiskScore that was computed before that claim arrived may now be
stale and needs to be recomputed.

The Pipeline class is the right tool for *new* events but always starts
at Triage, which is gated on (event family, kind). The rescore path is
different: we already know which dimension to rescore (the member already
has a RiskScore in that dimension), so we synthesize a CARE_MGMT trigger
event, set ctx.use_case directly, and run only Enrichment -> Scoring ->
Recommendation. Outputs go through the same persistence path so the new
RiskScore lands in risk_history exactly like a fresh score, with a new
CaseFile capturing the rescore inputs.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

import structlog

from ..member_events.schemas import EventFamily, MemberEvent
from ..member_record.mongo import MongoStore
from ..member_record.schemas import CaseFile, RiskDimension
from .base import Agent, PipelineCtx
from .enrichment import EnrichmentAgent
from .recommendation import RecommendationAgent
from .scoring import ScoringAgent

_RESCORE_KIND = "rescore_trigger"


class Rescorer:
    """Re-runs Enrichment -> Scoring -> Recommendation for one dimension.

    Persists a fresh RiskScore + Disposition + immutable CaseFile so the
    rescore is auditable next to the original decision. The same agent
    knobs Pipeline accepts work here too — pass an AdkScoringAgent for an
    LLM-driven rescore, or leave the defaults for the deterministic path.
    """

    def __init__(
        self,
        store: MongoStore,
        *,
        scoring_agent: Agent | None = None,
        recommendation_agent: Agent | None = None,
        enrichment_agent: Agent | None = None,
        model_version: str = "v0.0.1-rules-rescore",
    ) -> None:
        self._store = store
        self._enrichment = enrichment_agent or EnrichmentAgent(store)
        self._scoring = scoring_agent or ScoringAgent()
        self._recommendation = recommendation_agent or RecommendationAgent()
        self._model_version = model_version
        self._log = structlog.get_logger(__name__)

    async def rescore(
        self,
        member_id: str,
        dimension: RiskDimension,
        *,
        trigger_event_id: str | None = None,
    ) -> PipelineCtx:
        """Re-evaluate one dimension. Returns the final PipelineCtx."""
        log = self._log.bind(
            member_id=member_id,
            dimension=dimension.value,
            payer_org_id=self._store.payer_org_id,
            trigger=trigger_event_id,
        )
        ctx = PipelineCtx(
            event=self._build_trigger_event(member_id),
            payer_org_id=self._store.payer_org_id,
            use_case=dimension,
        )
        log.info("rescore.start")

        ctx = await self._enrichment.run(ctx)
        ctx = await self._scoring.run(ctx)
        ctx = await self._recommendation.run(ctx)

        if ctx.risk_score is not None:
            self._store.save_risk_score(ctx.risk_score)
        if ctx.disposition is not None:
            self._store.save_disposition(ctx.disposition)
            self._store.save_case_file(self._build_case_file(ctx, trigger_event_id))
        log.info(
            "rescore.complete",
            score=ctx.risk_score.score if ctx.risk_score else None,
            action=ctx.disposition.action.value if ctx.disposition else None,
        )
        return ctx

    # ------------------------------------------------------------------

    def _build_trigger_event(self, member_id: str) -> MemberEvent:
        now = datetime.now(tz=timezone.utc)
        return MemberEvent(
            event_id=f"rescore-{uuid.uuid4()}",
            member_id=member_id,
            family=EventFamily.CARE_MGMT,
            kind=_RESCORE_KIND,
            ts=now,
            source_system="rescore-worker",
            attributes={},
            payload_hash="rescore",
            received_at=now,
        )

    def _build_case_file(
        self,
        ctx: PipelineCtx,
        trigger_event_id: str | None,
    ) -> CaseFile:
        if ctx.disposition is None:  # pragma: no cover
            raise RuntimeError("CaseFile requires a Disposition")
        inputs = {
            "rescore": True,
            "trigger_event_id": trigger_event_id,
            "member_id": ctx.event.member_id,
            "use_case": ctx.use_case.value if ctx.use_case else None,
            "recent_event_ids": [
                e.get("event_id") for e in ctx.recent_events if e.get("event_id")
            ],
        }
        return CaseFile(
            payer_org_id=ctx.payer_org_id,
            case_file_id=str(uuid.uuid4()),
            member_id=ctx.event.member_id,
            disposition_id=ctx.disposition.disposition_id,
            inputs_hash=hashlib.sha256(
                json.dumps(inputs, sort_keys=True, default=str).encode("utf-8"),
            ).hexdigest(),
            agent_trace=list(ctx.audit_trace),
            model_version=self._model_version,
            produced_at=datetime.now(tz=timezone.utc),
        )
