"""Pipeline — composes the four care_decisioning agents into one async run.

Responsibilities:
    1. Persist the inbound MemberEvent (idempotent — replays are safe).
    2. Run Triage -> Enrichment -> Scoring -> Recommendation in order.
    3. If Triage skipped, log and return without writing outputs.
    4. Otherwise, persist the RiskScore, the Disposition, and an immutable
       CaseFile that captures the full agent_trace and an inputs_hash so a
       compliance reviewer can reconstruct exactly how the decision was
       made.
    5. Log every stage with structlog under a logger bound to event_id,
       member_id, and payer_org_id so log lines are always traceable.

This is the only module in the codebase that knows the order of the agents
and that calls the storage layer's write methods for the pipeline outputs.
Replacing a stage with a Google ADK agent later requires no changes here.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

import structlog

from member_event_stream_agent.member_events.schemas import MemberEvent
from member_event_stream_agent.member_record.mongo import MongoStore
from member_event_stream_agent.member_record.schemas import CaseFile

from .base import Agent, PipelineCtx
from .enrichment import EnrichmentAgent
from .recommendation import RecommendationAgent
from .scoring import ScoringAgent
from .triage import TriageAgent


class Pipeline:
    """Composes the four agents and persists the pipeline outputs.

    The agents themselves are stateless and rule-based; this class owns
    the orchestration, the storage write path, and the audit trail.
    """

    def __init__(
        self,
        store: MongoStore,
        *,
        model_version: str = "v0.0.1-rules",
        scoring_agent: Agent | None = None,
        triage_agent: Agent | None = None,
        enrichment_agent: Agent | None = None,
        recommendation_agent: Agent | None = None,
    ) -> None:
        self._store = store
        self._model_version = model_version
        self._stages: tuple[Agent, ...] = (
            triage_agent or TriageAgent(),
            enrichment_agent or EnrichmentAgent(store),
            scoring_agent or ScoringAgent(),
            recommendation_agent or RecommendationAgent(),
        )
        self._log = structlog.get_logger(__name__)

    async def process(self, event: MemberEvent) -> PipelineCtx:
        """Run one event end to end. Returns the final PipelineCtx."""
        ctx = PipelineCtx(event=event, payer_org_id=self._store.payer_org_id)
        log = self._log.bind(
            event_id=event.event_id,
            member_id=event.member_id,
            payer_org_id=ctx.payer_org_id,
        )
        log.info("pipeline.start")

        # 1. Persist the inbound event (idempotent on event_id)
        inserted = self._store.save_event(event.model_dump(mode="json"))
        log.info("pipeline.event_persisted", inserted=inserted)

        # 2. Run each stage
        for agent in self._stages:
            ctx = await agent.run(ctx)
            log.info(
                "pipeline.stage",
                stage=agent.name,
                skip=ctx.skip,
                has_risk_score=ctx.risk_score is not None,
                has_disposition=ctx.disposition is not None,
            )
            if ctx.skip:
                log.info("pipeline.skipped", reason=ctx.skip_reason)
                return ctx

        # 3. Persist outputs (skip-safe: every stage above produced what
        #    it should). Order matters — score must land before disposition,
        #    disposition before its CaseFile, so the foreign-key-ish refs
        #    are always valid even if a later write fails.
        if ctx.risk_score is not None:
            self._store.save_risk_score(ctx.risk_score)
        if ctx.disposition is not None:
            self._store.save_disposition(ctx.disposition)
            case_file = self._build_case_file(ctx)
            self._store.save_case_file(case_file)
            log.info(
                "pipeline.complete",
                action=ctx.disposition.action.value,
                score=ctx.risk_score.score if ctx.risk_score else None,
                case_file_id=case_file.case_file_id,
            )
        return ctx

    # ------------------------------------------------------------------

    def _build_case_file(self, ctx: PipelineCtx) -> CaseFile:
        if ctx.disposition is None:  # pragma: no cover - guarded by caller
            raise RuntimeError("CaseFile requires a Disposition")
        return CaseFile(
            payer_org_id=ctx.payer_org_id,
            case_file_id=str(uuid.uuid4()),
            member_id=ctx.event.member_id,
            disposition_id=ctx.disposition.disposition_id,
            inputs_hash=self._hash_inputs(ctx),
            agent_trace=list(ctx.audit_trace),
            model_version=self._model_version,
            produced_at=datetime.now(tz=timezone.utc),
        )

    def _hash_inputs(self, ctx: PipelineCtx) -> str:
        """Stable SHA-256 of the inputs the pipeline acted on.

        A reviewer can recompute this hash from the persisted event +
        recent_events snapshot to verify the decision was made over the
        exact same inputs that landed at the time.
        """
        payload = {
            "event_id": ctx.event.event_id,
            "event_payload_hash": ctx.event.payload_hash,
            "member_id": ctx.event.member_id,
            "recent_event_ids": [
                e.get("event_id") for e in ctx.recent_events if e.get("event_id")
            ],
            "use_case": ctx.use_case.value if ctx.use_case else None,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        ).hexdigest()
