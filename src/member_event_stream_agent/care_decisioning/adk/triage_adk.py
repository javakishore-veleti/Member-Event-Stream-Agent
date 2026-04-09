"""ADK-backed TriageAgent.

Asks the LLM to classify the inbound MemberEvent into one of the supported
RiskDimension values (or None to skip). Falls back to the rule-based
TriageAgent on LLM error or when the response cannot be coerced into a
known dimension — same audit-trail discipline as AdkScoringAgent so a
reviewer always knows whether a decision was LLM- or rule-driven.
"""
from __future__ import annotations

import structlog

from ...member_record.schemas import RiskDimension
from ..base import PipelineCtx
from ..triage import TriageAgent
from .llm import LlmClient, TriageResponse

_PROMPT = (
    "You triage healthcare member events for a US health-plan payer. Given\n"
    "an inbound event family + kind and the recent event history, choose at\n"
    "most one RiskDimension this event should drive (readmission, care_gap,\n"
    "adherence, polypharmacy, fwa, pa_decision) — or null if the event is\n"
    "not actionable. Return strict JSON with keys use_case and rationale."
)


def _coerce_use_case(raw: str | None) -> RiskDimension | None:
    if raw is None:
        return None
    try:
        return RiskDimension(raw.strip().lower())
    except ValueError:
        return None


class AdkTriageAgent:
    name: str = "triage_adk"

    def __init__(
        self,
        client: LlmClient,
        *,
        fallback: TriageAgent | None = None,
    ) -> None:
        self._client = client
        self._fallback = fallback or TriageAgent()
        self._log = structlog.get_logger(__name__)

    async def run(self, ctx: PipelineCtx) -> PipelineCtx:
        context = {
            "event": {
                "family": ctx.event.family.value,
                "kind": ctx.event.kind,
            },
            "recent_event_kinds": [
                e.get("kind") for e in ctx.recent_events[:10] if e.get("kind")
            ],
        }
        try:
            response: TriageResponse = await self._client.complete_triage(
                prompt=_PROMPT,
                context=context,
            )
        except Exception as exc:  # noqa: BLE001 — intentional broad fall-back
            self._log.warning("triage_adk.fallback", error=str(exc))
            ctx.trace(self.name, fallback=True, error=str(exc))
            return await self._fallback.run(ctx)

        use_case = _coerce_use_case(response.use_case)
        if use_case is None:
            ctx.skip = True
            ctx.skip_reason = response.rationale or "adk classified as non-actionable"
            ctx.trace(self.name, source="adk", skip=True, reason=ctx.skip_reason)
            return ctx

        ctx.use_case = use_case
        ctx.trace(
            self.name,
            source="adk",
            use_case=use_case.value,
            rationale=response.rationale,
        )
        return ctx
