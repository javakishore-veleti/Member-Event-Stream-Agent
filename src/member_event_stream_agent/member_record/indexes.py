"""Declarative MongoDB index specs for the member_record store.

These specs are applied by MongoStore on first connect. Adding an index here
plus a re-deploy is the only step to roll out a new index — we never call
create_index from business logic.
"""
from __future__ import annotations

from typing import NamedTuple

from pymongo import ASCENDING, DESCENDING


class IndexSpec(NamedTuple):
    keys: list[tuple[str, int]]
    name: str
    unique: bool = False


# Collection name -> list of index specs for that collection.
INDEX_SPECS: dict[str, list[IndexSpec]] = {
    "members": [
        IndexSpec(
            keys=[("payer_org_id", ASCENDING), ("member_id", ASCENDING)],
            name="ux_members_tenant_member",
            unique=True,
        ),
    ],
    "events": [
        # Idempotency: claims and ADT feeds are notoriously replayed. We
        # dedupe on (payer_org_id, event_id) so retries are safe.
        IndexSpec(
            keys=[("payer_org_id", ASCENDING), ("event_id", ASCENDING)],
            name="ux_events_tenant_event_id",
            unique=True,
        ),
        IndexSpec(
            keys=[
                ("payer_org_id", ASCENDING),
                ("member_id", ASCENDING),
                ("ts", DESCENDING),
            ],
            name="ix_events_tenant_member_ts",
        ),
    ],
    "risk_scores": [
        IndexSpec(
            keys=[
                ("payer_org_id", ASCENDING),
                ("member_id", ASCENDING),
                ("dimension", ASCENDING),
                ("produced_at", DESCENDING),
            ],
            name="ix_risk_scores_tenant_member_dim",
        ),
    ],
    "dispositions": [
        IndexSpec(
            keys=[
                ("payer_org_id", ASCENDING),
                ("member_id", ASCENDING),
                ("produced_at", DESCENDING),
            ],
            name="ix_dispositions_tenant_member",
        ),
    ],
    "case_files": [
        IndexSpec(
            keys=[("payer_org_id", ASCENDING), ("disposition_id", ASCENDING)],
            name="ux_case_files_tenant_disposition",
            unique=True,
        ),
    ],
}
