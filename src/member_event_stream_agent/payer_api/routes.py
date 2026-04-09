"""Read-side HTTP routes for clinical and operational staff.

Surface is intentionally narrow for the 2-hour slice:
    GET /members/{member_id}                 -> Member 360 head record
    GET /members/{member_id}/risk-history    -> recent risk scores by dimension
    GET /members/{member_id}/recent-events   -> last N normalized events

Writes flow through the worker (member_events.consumer -> Pipeline) — this
router is read-only on purpose so the surface stays safe to expose to
analysts and to the MCP gateway.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..member_record.mongo import MongoStore
from ..member_record.schemas import RiskDimension
from .deps import StoreDep

router = APIRouter(prefix="/members", tags=["members"])


@router.get("/{member_id}")
def get_member(member_id: str, store: MongoStore = StoreDep) -> dict[str, Any]:
    member = store.get_member(member_id)
    if member is None:
        raise HTTPException(status_code=404, detail="member not found")
    return member.model_dump(mode="json")


@router.get("/{member_id}/recent-events")
def get_recent_events(
    member_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    store: MongoStore = StoreDep,
) -> dict[str, Any]:
    events = store.get_recent_events(member_id, limit=limit)
    return {"member_id": member_id, "count": len(events), "events": events}


@router.get("/{member_id}/risk-history")
def get_risk_history(
    member_id: str,
    dimension: RiskDimension = Query(...),
    limit: int = Query(default=20, ge=1, le=200),
    store: MongoStore = StoreDep,
) -> dict[str, Any]:
    scores = store.get_risk_history(member_id, dimension, limit=limit)
    return {
        "member_id": member_id,
        "dimension": dimension.value,
        "count": len(scores),
        "scores": [s.model_dump(mode="json") for s in scores],
    }
