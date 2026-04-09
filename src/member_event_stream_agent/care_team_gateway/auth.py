"""Token + scope enforcement and HIPAA audit hook for the MCP gateway.

The gateway is the only egress path for member data toward LLM clients used
by care managers, utilization managers, pharmacists, quality/HEDIS analysts,
and FWA investigators. Every call must:

    1. present a bearer token that matches MCP_TOKEN,
    2. carry a scope that the tool declares it accepts,
    3. produce an audit-log entry capturing who, what, when, which member.

The audit logger is intentionally an in-process structlog call for this
slice. In production it lands in an immutable HIPAA audit store; the
seam (audit_phi_access) is in place so swapping the sink is a one-line
change at the call site, not a refactor.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import structlog

from ..config import get_settings


class AuthError(Exception):
    """Raised when a caller fails token or scope checks."""


# Persona scopes recognized by the gateway. Tools declare which subset they
# accept; the wrapper rejects everything else.
VALID_SCOPES: frozenset[str] = frozenset(
    {"care_manager", "um", "pharmacist", "quality", "fwa"},
)


@dataclass(frozen=True)
class CallerIdentity:
    """Resolved caller after a successful auth check."""

    caller_id: str
    scope: str


def authenticate(token: str | None, scope: str | None, caller_id: str | None) -> CallerIdentity:
    """Verify the token + scope. Returns a CallerIdentity or raises AuthError."""
    settings = get_settings()
    if not token or token != settings.mcp_token:
        raise AuthError("invalid or missing token")
    if not scope or scope not in VALID_SCOPES:
        raise AuthError(f"invalid scope: {scope!r}")
    if not caller_id:
        raise AuthError("caller_id required")
    return CallerIdentity(caller_id=caller_id, scope=scope)


def require_scope(caller: CallerIdentity, allowed: Iterable[str]) -> None:
    if caller.scope not in set(allowed):
        raise AuthError(
            f"scope {caller.scope!r} not permitted; tool allows {sorted(allowed)!r}",
        )


def audit_phi_access(
    *,
    caller: CallerIdentity,
    tool: str,
    member_id: str | None,
    payer_org_id: str,
    outcome: str,
) -> dict[str, object]:
    """Append one HIPAA-grade access record. Returns the record for tests."""
    record = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "caller_id": caller.caller_id,
        "scope": caller.scope,
        "tool": tool,
        "member_id": member_id,
        "payer_org_id": payer_org_id,
        "outcome": outcome,
    }
    structlog.get_logger("care_team_gateway.audit").info("phi_access", **record)
    return record
