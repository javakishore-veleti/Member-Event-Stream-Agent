"""MCP tool functions exposed to LLM clients used by the care team.

Each tool is a thin wrapper around MongoStore that:

    1. Authenticates the caller and enforces the tool's allowed scopes.
    2. Reads the data from the payer-scoped MongoStore.
    3. Redacts PHI fields on the response (the gateway is the only egress
       path, so redaction must happen here, not at the caller).
    4. Writes one HIPAA audit record per call via auth.audit_phi_access.

The Member 360 schemas tag PHI via Field(json_schema_extra={"phi": True}).
We honor those tags when building the response so adding a new PHI field
to the schemas does not silently leak through this gateway.
"""
from __future__ import annotations

from typing import Any, Iterable

from ..member_record.mongo import MongoStore
from ..member_record.schemas import Member
from .auth import (
    CallerIdentity,
    audit_phi_access,
    authenticate,
    require_scope,
)

REDACTED = "***REDACTED***"


def _phi_field_names(model_cls: type) -> set[str]:
    """Return the set of field names that the schema tags as PHI."""
    out: set[str] = set()
    for name, field in model_cls.model_fields.items():
        extra = field.json_schema_extra
        if isinstance(extra, dict) and extra.get("phi"):
            out.add(name)
    return out


_MEMBER_PHI_FIELDS = _phi_field_names(Member)


def _redact_member(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: (REDACTED if k in _MEMBER_PHI_FIELDS else v) for k, v in payload.items()}


def _redact_event(event: dict[str, Any]) -> dict[str, Any]:
    """Strip free-form attributes; keep envelope fields safe to surface."""
    safe_keys = {"event_id", "member_id", "family", "kind", "ts", "source_system"}
    return {k: v for k, v in event.items() if k in safe_keys}


# ---------------------------------------------------------------------------
# Tool entry points
# ---------------------------------------------------------------------------

ALL_PERSONAS: tuple[str, ...] = ("care_manager", "um", "pharmacist", "quality", "fwa")


def _resolve_caller(
    *,
    token: str | None,
    scope: str | None,
    caller_id: str | None,
    allowed: Iterable[str],
) -> CallerIdentity:
    caller = authenticate(token, scope, caller_id)
    require_scope(caller, allowed)
    return caller


def member_lookup(
    member_id: str,
    *,
    store: MongoStore,
    token: str | None,
    scope: str | None,
    caller_id: str | None,
) -> dict[str, Any]:
    """Return one member record with PHI fields redacted."""
    caller = _resolve_caller(token=token, scope=scope, caller_id=caller_id, allowed=ALL_PERSONAS)
    member = store.get_member(member_id)
    if member is None:
        audit_phi_access(
            caller=caller,
            tool="member_lookup",
            member_id=member_id,
            payer_org_id=store.payer_org_id,
            outcome="not_found",
        )
        return {"found": False, "member_id": member_id}
    audit_phi_access(
        caller=caller,
        tool="member_lookup",
        member_id=member_id,
        payer_org_id=store.payer_org_id,
        outcome="ok",
    )
    return {"found": True, "member": _redact_member(member.model_dump(mode="json"))}


def pa_queue(
    *,
    limit: int = 50,
    store: MongoStore,
    token: str | None,
    scope: str | None,
    caller_id: str | None,
) -> dict[str, Any]:
    """Open prior-authorization queue for UM nurses and clinical pharmacists.

    Returns dispositions whose action requires clinical workup
    (queue_pa_review, draft_pa_response, propose_intervention). PHI is
    not present in dispositions, but the audit hook still records access.
    """
    caller = _resolve_caller(
        token=token, scope=scope, caller_id=caller_id, allowed=("um", "pharmacist"),
    )
    items = store.get_pa_queue(limit=limit)
    audit_phi_access(
        caller=caller,
        tool="pa_queue",
        member_id=None,
        payer_org_id=store.payer_org_id,
        outcome="ok",
    )
    return {"count": len(items), "dispositions": items}


def panel_overview(
    provider_id: str,
    *,
    limit: int = 100,
    store: MongoStore,
    token: str | None,
    scope: str | None,
    caller_id: str | None,
) -> dict[str, Any]:
    """Care manager / quality view of one PCP's assigned member panel.

    Returns redacted member head records — same PHI policy as member_lookup.
    """
    caller = _resolve_caller(
        token=token,
        scope=scope,
        caller_id=caller_id,
        allowed=("care_manager", "quality"),
    )
    members = store.get_members_by_pcp(provider_id, limit=limit)
    audit_phi_access(
        caller=caller,
        tool="panel_overview",
        member_id=None,
        payer_org_id=store.payer_org_id,
        outcome="ok",
    )
    return {
        "provider_id": provider_id,
        "count": len(members),
        "members": [_redact_member(m) for m in members],
    }


def cohort_overview(
    *,
    min_score: float = 0.5,
    store: MongoStore,
    token: str | None,
    scope: str | None,
    caller_id: str | None,
) -> dict[str, Any]:
    """Population-level risk distribution by RiskDimension.

    Aggregate read — no PHI returned, but still scoped + audited.
    """
    caller = _resolve_caller(
        token=token,
        scope=scope,
        caller_id=caller_id,
        allowed=("quality", "fwa", "um"),
    )
    rows = store.aggregate_risk_by_dimension(min_score=min_score)
    audit_phi_access(
        caller=caller,
        tool="cohort_overview",
        member_id=None,
        payer_org_id=store.payer_org_id,
        outcome="ok",
    )
    return {"min_score": min_score, "rows": rows}


def related_entities(
    member_id: str,
    *,
    store: MongoStore,
    token: str | None,
    scope: str | None,
    caller_id: str | None,
) -> dict[str, Any]:
    """Distinct source systems, event families, and kinds touching one member.

    Lets an analyst see "what's been going on" without paging raw events.
    Open to all personas because the response carries no PHI fields.
    """
    caller = _resolve_caller(
        token=token, scope=scope, caller_id=caller_id, allowed=ALL_PERSONAS,
    )
    summary = store.get_related_entities(member_id)
    audit_phi_access(
        caller=caller,
        tool="related_entities",
        member_id=member_id,
        payer_org_id=store.payer_org_id,
        outcome="ok",
    )
    return summary


def recent_events(
    member_id: str,
    *,
    limit: int = 20,
    store: MongoStore,
    token: str | None,
    scope: str | None,
    caller_id: str | None,
) -> dict[str, Any]:
    """Return the last N normalized events for a member with attributes stripped."""
    caller = _resolve_caller(
        token=token,
        scope=scope,
        caller_id=caller_id,
        allowed=("care_manager", "um", "pharmacist", "quality", "fwa"),
    )
    events = store.get_recent_events(member_id, limit=limit)
    audit_phi_access(
        caller=caller,
        tool="recent_events",
        member_id=member_id,
        payer_org_id=store.payer_org_id,
        outcome="ok",
    )
    return {
        "member_id": member_id,
        "count": len(events),
        "events": [_redact_event(e) for e in events],
    }
