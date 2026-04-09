"""TriageAgent — classify the inbound event into one of the named use cases.

Block 4 implements the routing as a small static table. The Triage stage:
    - already-noise events were dropped by the normalizer, so this stage
      does not need to repeat that filter;
    - decides which RiskDimension (use case) the event belongs to so the
      Scoring stage knows which rules to apply;
    - if no use case matches, marks the context as skip=True so downstream
      stages no-op cleanly.

The mapping is conservative on purpose. We add a use case for an event
family + kind combination only when there is a defensible rule the Scoring
stage actually implements; everything else is skipped.
"""
from __future__ import annotations

from member_event_stream_agent.member_record.schemas import RiskDimension

from .base import Agent, PipelineCtx

# (family, kind) -> use case dimension
_TRIAGE_RULES: dict[tuple[str, str], RiskDimension] = {
    ("ENCOUNTER", "inpatient_discharge"): RiskDimension.READMISSION,
    ("ENCOUNTER", "inpatient_admit"): RiskDimension.READMISSION,
    ("ENCOUNTER", "ed_visit"): RiskDimension.READMISSION,
    ("ENCOUNTER", "office_visit"): RiskDimension.CARE_GAP,
    ("ENCOUNTER", "telehealth_visit"): RiskDimension.CARE_GAP,
    ("ELIGIBILITY", "member_enrolled"): RiskDimension.CARE_GAP,
    ("ELIGIBILITY", "plan_changed"): RiskDimension.CARE_GAP,
    ("PHARMACY", "rx_filled"): RiskDimension.POLYPHARMACY,
    ("PHARMACY", "prior_auth_requested"): RiskDimension.PA_DECISION,
    ("LAB", "lab_resulted"): RiskDimension.CARE_GAP,
    ("LAB", "lab_abnormal_flagged"): RiskDimension.CARE_GAP,
    ("CLAIM", "claim_received"): RiskDimension.FWA,
}


class TriageAgent:
    name: str = "triage"

    async def run(self, ctx: PipelineCtx) -> PipelineCtx:
        key = (ctx.event.family.value, ctx.event.kind)
        use_case = _TRIAGE_RULES.get(key)

        if use_case is None:
            ctx.skip = True
            ctx.skip_reason = (
                f"no use case mapped for {ctx.event.family.value}/{ctx.event.kind}"
            )
            ctx.trace(self.name, skip=True, reason=ctx.skip_reason)
            return ctx

        ctx.use_case = use_case
        ctx.trace(self.name, use_case=use_case.value)
        return ctx
