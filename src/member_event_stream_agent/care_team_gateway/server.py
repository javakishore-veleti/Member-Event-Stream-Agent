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

    return server
