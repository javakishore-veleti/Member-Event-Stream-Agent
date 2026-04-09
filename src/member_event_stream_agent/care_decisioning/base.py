"""Agent Protocol and the shared PipelineCtx that flows through the pipeline.

The Agent Protocol is intentionally tiny so the four built-in agents can be
swapped, individually or wholesale, for Google ADK agents later without any
caller-side change. Block 4 ships rule-based stubs against this Protocol;
the LLM-backed implementations land in a later iteration.

PipelineCtx carries every piece of state any stage might need to read or
write — the event itself, the loaded Member 360 context, the agent
classifications, the produced RiskScore, the chosen Disposition, and an
append-only audit_trace. CaseFile (in member_record) is built from
audit_trace at the end of the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from member_event_stream_agent.member_events.schemas import MemberEvent
from member_event_stream_agent.member_record.schemas import (
    Disposition,
    Member,
    RiskDimension,
    RiskScore,
)


@dataclass
class PipelineCtx:
    """Mutable state passed through every agent in the pipeline.

    Stages set fields they own and append to audit_trace; they should not
    overwrite fields owned by earlier stages. Block 5 wires this together.
    """

    event: MemberEvent
    payer_org_id: str

    # Set by TriageAgent
    use_case: RiskDimension | None = None
    skip: bool = False
    skip_reason: str | None = None

    # Set by EnrichmentAgent
    member: Member | None = None
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    narrative: str | None = None  # Optional LLM-summarized timeline

    # Set by ScoringAgent
    risk_score: RiskScore | None = None

    # Set by RecommendationAgent
    disposition: Disposition | None = None

    # Appended to by every stage
    audit_trace: list[dict[str, Any]] = field(default_factory=list)

    def trace(self, stage: str, **fields: Any) -> None:
        """Append one stage entry to the audit trace."""
        self.audit_trace.append({"stage": stage, **fields})


class Agent(Protocol):
    """One stage of the care_decisioning pipeline.

    Implementations may be rule-based (Block 4) or LLM-backed via Google ADK
    (later). Either way the contract is identical: take a PipelineCtx, do
    your work, append your audit trace entry, and return the same context.
    """

    name: str

    async def run(self, ctx: PipelineCtx) -> PipelineCtx:
        ...
