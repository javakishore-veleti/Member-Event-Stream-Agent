"""FastMCP server registration for the care_team_gateway tools.

The server is built lazily because fastmcp is an optional runtime dep — the
test suite calls the tool functions in tools.py directly to keep the suite
offline. main.py imports build_mcp_server only at process startup.

Both registered tools delegate straight to the corresponding function in
tools.py, which already runs auth, scope check, redaction, and audit-log
emission. The server module is therefore very thin on purpose.
"""
from __future__ import annotations

from typing import Any

from ..member_record.mongo import MongoStore
from . import tools as gw_tools


def build_mcp_server(store: MongoStore) -> Any:
    """Construct a FastMCP server with the gateway's tools registered."""
    from fastmcp import FastMCP

    server = FastMCP("care-team-gateway")

    @server.tool()
    def member_lookup(
        member_id: str,
        token: str,
        scope: str,
        caller_id: str,
    ) -> dict[str, Any]:
        """Look up one Member 360 head record. PHI fields are redacted."""
        return gw_tools.member_lookup(
            member_id,
            store=store,
            token=token,
            scope=scope,
            caller_id=caller_id,
        )

    @server.tool()
    def recent_events(
        member_id: str,
        token: str,
        scope: str,
        caller_id: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Return the last N normalized events for a member."""
        return gw_tools.recent_events(
            member_id,
            limit=limit,
            store=store,
            token=token,
            scope=scope,
            caller_id=caller_id,
        )

    @server.tool()
    def pa_queue(
        token: str,
        scope: str,
        caller_id: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Open prior-authorization queue (UM / clinical pharmacy)."""
        return gw_tools.pa_queue(
            limit=limit, store=store, token=token, scope=scope, caller_id=caller_id,
        )

    @server.tool()
    def panel_overview(
        provider_id: str,
        token: str,
        scope: str,
        caller_id: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Members assigned to one PCP — care manager / quality view."""
        return gw_tools.panel_overview(
            provider_id,
            limit=limit,
            store=store,
            token=token,
            scope=scope,
            caller_id=caller_id,
        )

    @server.tool()
    def cohort_overview(
        token: str,
        scope: str,
        caller_id: str,
        min_score: float = 0.5,
    ) -> dict[str, Any]:
        """Population risk counts by RiskDimension at or above min_score."""
        return gw_tools.cohort_overview(
            min_score=min_score,
            store=store,
            token=token,
            scope=scope,
            caller_id=caller_id,
        )

    @server.tool()
    def related_entities(
        member_id: str,
        token: str,
        scope: str,
        caller_id: str,
    ) -> dict[str, Any]:
        """Distinct source systems, families, and kinds touching one member."""
        return gw_tools.related_entities(
            member_id,
            store=store,
            token=token,
            scope=scope,
            caller_id=caller_id,
        )

    return server
