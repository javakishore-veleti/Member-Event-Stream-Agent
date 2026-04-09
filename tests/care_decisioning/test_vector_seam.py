"""Tests for the vector seam: parser, FakeVectorClient, MultiVectorClient,
factory selection, and AdkEnrichmentAgent integration.

Stays offline — no real vector backend is exercised. The factory tests
verify that comma-separated provider lists parse correctly and the
``all`` shorthand expands to every real backend.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import mongomock
import pytest

from member_event_stream_agent.care_decisioning.adk.enrichment_adk import (
    AdkEnrichmentAgent,
)
from member_event_stream_agent.care_decisioning.adk.llm import (
    FakeLlmClient,
    NarrativeResponse,
)
from member_event_stream_agent.care_decisioning.base import PipelineCtx
from member_event_stream_agent.care_decisioning.vector.base import (
    FakeVectorClient,
    VectorHit,
)
from member_event_stream_agent.care_decisioning.vector.factory import (
    build_vector_client,
    parse_providers,
)
from member_event_stream_agent.care_decisioning.vector.multi import MultiVectorClient
from member_event_stream_agent.config import Settings
from member_event_stream_agent.member_events.schemas import EventFamily, MemberEvent
from member_event_stream_agent.member_record.mongo import MongoStore
from member_event_stream_agent.member_record.schemas import (
    LineOfBusiness,
    Member,
    RiskDimension,
)


# ---------------------------------------------------------------------------
# Provider parsing
# ---------------------------------------------------------------------------


def test_parse_providers_default_is_stub() -> None:
    assert parse_providers("") == ["stub"]


def test_parse_providers_csv_lowercases_and_strips() -> None:
    assert parse_providers("Qdrant, Weaviate ,Chroma") == [
        "qdrant",
        "weaviate",
        "chroma",
    ]


def test_parse_providers_all_expands_to_every_backend() -> None:
    assert parse_providers("all") == [
        "qdrant",
        "weaviate",
        "chroma",
        "milvus",
        "pgvector",
    ]


def test_parse_providers_all_among_others_still_expands() -> None:
    assert parse_providers("stub,all") == [
        "qdrant",
        "weaviate",
        "chroma",
        "milvus",
        "pgvector",
    ]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_default_is_fake() -> None:
    client = build_vector_client(Settings(VECTOR_PROVIDER="stub"))
    assert isinstance(client, FakeVectorClient)


def test_factory_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="unknown VECTOR_PROVIDER"):
        build_vector_client(Settings(VECTOR_PROVIDER="not-real"))


def test_factory_multi_with_two_stubs() -> None:
    """Two ``stub`` entries build a MultiVectorClient over two FakeVectorClients
    so the multi path is exercised offline."""
    client = build_vector_client(Settings(VECTOR_PROVIDER="stub,stub"))
    assert isinstance(client, MultiVectorClient)
    assert client.backends == ["stub", "stub"]


# ---------------------------------------------------------------------------
# MultiVectorClient fan-out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_search_merges_and_dedupes() -> None:
    a = FakeVectorClient(hits=[VectorHit(id="x", score=0.5), VectorHit(id="y", score=0.4)])
    b = FakeVectorClient(hits=[VectorHit(id="x", score=0.9), VectorHit(id="z", score=0.3)])
    multi = MultiVectorClient([("a", a), ("b", b)])

    out = await multi.search_similar_contexts(query_text="q", member_id="M1", k=5)

    by_id = {h.id: h.score for h in out}
    # x kept the better score from b
    assert by_id == {"x": 0.9, "y": 0.4, "z": 0.3}
    # sorted by score desc
    assert [h.id for h in out] == ["x", "y", "z"]


@pytest.mark.asyncio
async def test_multi_search_tolerates_one_failing_backend() -> None:
    good = FakeVectorClient(hits=[VectorHit(id="x", score=0.5)])
    bad = FakeVectorClient(raise_on_next=True)
    multi = MultiVectorClient([("good", good), ("bad", bad)])

    out = await multi.search_similar_contexts(query_text="q", member_id="M1")
    assert [h.id for h in out] == ["x"]  # bad backend didn't take everything down


@pytest.mark.asyncio
async def test_multi_upsert_fans_out_to_all_backends() -> None:
    a = FakeVectorClient()
    b = FakeVectorClient()
    multi = MultiVectorClient([("a", a), ("b", b)])

    await multi.upsert_context(doc_id="d1", text="hello", member_id="M1", metadata={})

    assert len(a.upsert_calls) == 1
    assert len(b.upsert_calls) == 1
    assert a.upsert_calls[0]["doc_id"] == "d1"
    assert b.upsert_calls[0]["doc_id"] == "d1"


@pytest.mark.asyncio
async def test_multi_upsert_tolerates_one_failing_backend() -> None:
    good = FakeVectorClient()
    bad = FakeVectorClient(raise_on_next=True)
    multi = MultiVectorClient([("good", good), ("bad", bad)])

    await multi.upsert_context(doc_id="d1", text="t", member_id="M1")

    assert len(good.upsert_calls) == 1  # good still got it


# ---------------------------------------------------------------------------
# AdkEnrichmentAgent integration
# ---------------------------------------------------------------------------


def _store_with_member() -> MongoStore:
    store = MongoStore(mongomock.MongoClient(), "mesa_vec", "t1")
    store.save_member(
        Member(
            payer_org_id="t1",
            member_id="M1",
            plan_id="P1",
            line_of_business=LineOfBusiness.COMMERCIAL,
            eligibility_start=date(2024, 1, 1),
            dob_year=1980,
            zip3="021",
        ),
    )
    return store


def _event() -> MemberEvent:
    return MemberEvent(
        event_id="E1",
        member_id="M1",
        family=EventFamily.ENCOUNTER,
        kind="office_visit",
        ts=datetime.now(tz=timezone.utc),
        source_system="claims",
        attributes={},
        payload_hash="hash",
        received_at=datetime.now(tz=timezone.utc),
    )


@pytest.mark.asyncio
async def test_enrichment_attaches_similar_contexts() -> None:
    store = _store_with_member()
    llm = FakeLlmClient(narrative_responses=[NarrativeResponse(narrative="ok")])
    vec = FakeVectorClient(
        hits=[
            VectorHit(id="ctx-1", score=0.9, member_id="M2", text="similar past case"),
            VectorHit(id="ctx-2", score=0.8, member_id="M3", text="another"),
        ],
    )
    agent = AdkEnrichmentAgent(store, llm, vector_client=vec)
    ctx = PipelineCtx(event=_event(), payer_org_id="t1", use_case=RiskDimension.CARE_GAP)

    out = await agent.run(ctx)

    assert len(out.similar_contexts) == 2
    assert out.similar_contexts[0]["id"] == "ctx-1"
    assert any(t.get("vector") == "ok" for t in out.audit_trace)
    assert vec.search_calls and vec.search_calls[0]["member_id"] == "M1"


@pytest.mark.asyncio
async def test_enrichment_tolerates_vector_backend_failure() -> None:
    store = _store_with_member()
    llm = FakeLlmClient(narrative_responses=[NarrativeResponse(narrative="ok")])
    vec = FakeVectorClient(raise_on_next=True)
    agent = AdkEnrichmentAgent(store, llm, vector_client=vec)
    ctx = PipelineCtx(event=_event(), payer_org_id="t1", use_case=RiskDimension.CARE_GAP)

    out = await agent.run(ctx)

    assert out.similar_contexts == []  # graceful degradation
    assert any(t.get("vector") == "error" for t in out.audit_trace)
    # narrative still attached — vector failure didn't break enrichment
    assert out.narrative == "ok"


@pytest.mark.asyncio
async def test_enrichment_without_vector_client_is_unchanged() -> None:
    store = _store_with_member()
    llm = FakeLlmClient(narrative_responses=[NarrativeResponse(narrative="ok")])
    agent = AdkEnrichmentAgent(store, llm)  # no vector_client
    ctx = PipelineCtx(event=_event(), payer_org_id="t1", use_case=RiskDimension.CARE_GAP)

    out = await agent.run(ctx)

    assert out.similar_contexts == []
    assert out.narrative == "ok"
