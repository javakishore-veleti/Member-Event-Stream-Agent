"""End-to-end FastMCP server test (DoD #5).

Builds the real FastMCP server via build_mcp_server, connects to it with
fastmcp's in-process Client transport, and calls the registered
member_lookup tool over the actual MCP wire. Asserts the response
round-trips and that PHI fields are redacted on the way out — i.e. the
gateway is the only egress path and it actually redacts when called for
real, not just when the underlying tool function is invoked directly.
"""
from __future__ import annotations

from datetime import date

import mongomock
import pytest
from fastmcp import Client

from member_event_stream_agent.care_team_gateway.server import build_mcp_server
from member_event_stream_agent.care_team_gateway.tools import REDACTED
from member_event_stream_agent.member_record.mongo import MongoStore
from member_event_stream_agent.member_record.schemas import LineOfBusiness, Member


def _seeded_store() -> MongoStore:
    store = MongoStore(mongomock.MongoClient(), "mesa_mcp", "mcp-payer")
    store.save_member(
        Member(
            payer_org_id="mcp-payer",
            member_id="MCP-1",
            plan_id="P1",
            line_of_business=LineOfBusiness.COMMERCIAL,
            eligibility_start=date(2024, 1, 1),
            dob_year=1980,
            zip3="021",
        ),
    )
    return store


def _payload(result: object) -> dict:
    """fastmcp Client returns a CallToolResult; pull the structured payload."""
    data = getattr(result, "data", None)
    if data is not None:
        return data
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    return result  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_member_lookup_over_mcp_wire() -> None:
    server = build_mcp_server(_seeded_store())
    async with Client(server) as client:
        result = await client.call_tool(
            "member_lookup",
            {
                "member_id": "MCP-1",
                "token": "dev-token",
                "scope": "care_manager",
                "caller_id": "alice",
            },
        )
    payload = _payload(result)
    assert payload["found"] is True
    member = payload["member"]
    assert member["member_id"] == "MCP-1"
    assert member["dob_year"] == REDACTED
    assert member["zip3"] == REDACTED
