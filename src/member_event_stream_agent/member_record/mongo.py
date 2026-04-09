"""MongoStore — the only module that talks to MongoDB directly.

Wraps a pymongo.MongoClient and exposes typed save/get methods over the
member_record collections. Tenant isolation by payer_org_id is enforced
inside the class — callers cannot read or write outside their configured
tenant.

Construction
------------
- MongoStore(client, db_name, payer_org_id) — for tests, pass a mongomock
  client. For production, pass a real pymongo.MongoClient.
- MongoStore.from_uri(uri, db_name, payer_org_id) — convenience factory.

Idempotency
-----------
save_event uses an upsert keyed on (payer_org_id, event_id). Replays from
Kafka are safe — the second call returns inserted=False and does not write.
"""
from __future__ import annotations

from typing import Any

from .indexes import INDEX_SPECS
from .schemas import (
    CaseFile,
    Disposition,
    Member,
    RiskDimension,
    RiskScore,
)


class MongoStore:
    def __init__(self, client: Any, db_name: str, payer_org_id: str) -> None:
        self._client = client
        self._db = client[db_name]
        self._payer_org_id = payer_org_id
        self._indexes_applied = False

    @classmethod
    def from_uri(cls, uri: str, db_name: str, payer_org_id: str) -> "MongoStore":
        from pymongo import MongoClient

        return cls(MongoClient(uri), db_name, payer_org_id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def ensure_indexes(self) -> None:
        """Apply every index in indexes.INDEX_SPECS. Idempotent."""
        if self._indexes_applied:
            return
        for collection_name, specs in INDEX_SPECS.items():
            collection = self._db[collection_name]
            for spec in specs:
                collection.create_index(spec.keys, name=spec.name, unique=spec.unique)
        self._indexes_applied = True

    @property
    def payer_org_id(self) -> str:
        return self._payer_org_id

    def _scoped(self, query: dict[str, Any]) -> dict[str, Any]:
        """Inject the tenant filter into every read query."""
        return {**query, "payer_org_id": self._payer_org_id}

    # ------------------------------------------------------------------
    # Member
    # ------------------------------------------------------------------

    def save_member(self, member: Member) -> None:
        if member.payer_org_id != self._payer_org_id:
            raise ValueError(
                f"Member payer_org_id={member.payer_org_id!r} does not match store "
                f"payer_org_id={self._payer_org_id!r}",
            )
        self._db["members"].update_one(
            self._scoped({"member_id": member.member_id}),
            {"$set": member.model_dump(mode="json")},
            upsert=True,
        )

    def get_member(self, member_id: str) -> Member | None:
        doc = self._db["members"].find_one(self._scoped({"member_id": member_id}))
        if doc is None:
            return None
        doc.pop("_id", None)
        return Member.model_validate(doc)

    # ------------------------------------------------------------------
    # Events (the unified envelope landed here by member_events.consumer)
    # ------------------------------------------------------------------

    def save_event(self, event: dict[str, Any]) -> bool:
        """Idempotent insert of one MemberEvent envelope.

        Returns True if a new document was inserted, False if it was a
        duplicate of an event already on file.
        """
        if "event_id" not in event:
            raise ValueError("event must carry an event_id")
        scoped_event = {**event, "payer_org_id": self._payer_org_id}
        result = self._db["events"].update_one(
            self._scoped({"event_id": event["event_id"]}),
            {"$setOnInsert": scoped_event},
            upsert=True,
        )
        return result.upserted_id is not None

    def get_recent_events(self, member_id: str, limit: int = 50) -> list[dict[str, Any]]:
        cursor = (
            self._db["events"]
            .find(self._scoped({"member_id": member_id}))
            .sort("ts", -1)
            .limit(limit)
        )
        out: list[dict[str, Any]] = []
        for doc in cursor:
            doc.pop("_id", None)
            out.append(doc)
        return out

    # ------------------------------------------------------------------
    # Risk scores
    # ------------------------------------------------------------------

    def save_risk_score(self, score: RiskScore) -> None:
        if score.payer_org_id != self._payer_org_id:
            raise ValueError(
                f"RiskScore payer_org_id={score.payer_org_id!r} does not match store "
                f"payer_org_id={self._payer_org_id!r}",
            )
        self._db["risk_scores"].insert_one(score.model_dump(mode="json"))

    def get_risk_history(
        self,
        member_id: str,
        dimension: RiskDimension,
        limit: int = 20,
    ) -> list[RiskScore]:
        cursor = (
            self._db["risk_scores"]
            .find(self._scoped({"member_id": member_id, "dimension": dimension.value}))
            .sort("produced_at", -1)
            .limit(limit)
        )
        out: list[RiskScore] = []
        for doc in cursor:
            doc.pop("_id", None)
            out.append(RiskScore.model_validate(doc))
        return out

    # ------------------------------------------------------------------
    # Dispositions and case files
    # ------------------------------------------------------------------

    def save_disposition(self, disposition: Disposition) -> None:
        if disposition.payer_org_id != self._payer_org_id:
            raise ValueError("Disposition tenant mismatch")
        self._db["dispositions"].insert_one(disposition.model_dump(mode="json"))

    def save_case_file(self, case_file: CaseFile) -> None:
        if case_file.payer_org_id != self._payer_org_id:
            raise ValueError("CaseFile tenant mismatch")
        # Immutable: insert only, never update.
        self._db["case_files"].insert_one(case_file.model_dump(mode="json"))

    # ------------------------------------------------------------------
    # Care-team gateway read aggregations
    # ------------------------------------------------------------------

    def get_pa_queue(
        self,
        *,
        actions: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Dispositions awaiting clinical action — feeds the pa_queue tool.

        Defaults to actions that represent open work for utilization
        management and clinical pharmacy: queue_pa_review,
        draft_pa_response, and propose_intervention.
        """
        wanted = actions or [
            "queue_pa_review",
            "draft_pa_response",
            "propose_intervention",
        ]
        cursor = (
            self._db["dispositions"]
            .find(self._scoped({"action": {"$in": wanted}}))
            .sort("produced_at", -1)
            .limit(limit)
        )
        out: list[dict[str, Any]] = []
        for doc in cursor:
            doc.pop("_id", None)
            out.append(doc)
        return out

    def get_members_by_pcp(
        self,
        provider_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Members assigned to one PCP — feeds the panel_overview tool."""
        cursor = self._db["members"].find(
            self._scoped({"pcp_provider_id": provider_id}),
        ).limit(limit)
        out: list[dict[str, Any]] = []
        for doc in cursor:
            doc.pop("_id", None)
            out.append(doc)
        return out

    def aggregate_risk_by_dimension(
        self,
        *,
        min_score: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Counts of distinct members with score >= min_score per dimension.

        Feeds the cohort_overview tool. Returns a list of
        ``{"dimension": str, "members": int}`` rows sorted by dimension.
        """
        pipeline: list[dict[str, Any]] = [
            {"$match": self._scoped({"score": {"$gte": min_score}})},
            {"$group": {"_id": {"dimension": "$dimension", "member_id": "$member_id"}}},
            {"$group": {"_id": "$_id.dimension", "members": {"$sum": 1}}},
            {"$project": {"_id": 0, "dimension": "$_id", "members": 1}},
            {"$sort": {"dimension": 1}},
        ]
        return list(self._db["risk_scores"].aggregate(pipeline))

    def get_related_entities(
        self,
        member_id: str,
        *,
        recent_event_limit: int = 50,
    ) -> dict[str, Any]:
        """Distill the recent event timeline into related-entity buckets.

        Returns distinct source systems, event families, and event kinds the
        member has touched recently. Used by the related_entities MCP tool to
        give an analyst a one-shot picture of "what's been going on" without
        them paging through raw events.
        """
        events = self.get_recent_events(member_id, limit=recent_event_limit)
        source_systems: set[str] = set()
        families: set[str] = set()
        kinds: set[str] = set()
        for e in events:
            if e.get("source_system"):
                source_systems.add(str(e["source_system"]))
            if e.get("family"):
                families.add(str(e["family"]))
            if e.get("kind"):
                kinds.add(str(e["kind"]))
        return {
            "member_id": member_id,
            "event_count": len(events),
            "source_systems": sorted(source_systems),
            "families": sorted(families),
            "kinds": sorted(kinds),
        }
