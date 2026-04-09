"""FastAPI dependency wiring for the payer_api surface.

Single source of truth for how routes get a MongoStore and a Pipeline. The
underlying instances are constructed once at app-startup and stashed on
``application.state``; the Depends() helpers below just hand them back so
route signatures stay clean.

Selecting a backend:
    MONGO_URI=memory://   -> mongomock client (offline / tests / dev)
    MONGO_URI=mongodb://  -> real pymongo.MongoClient
"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, Request

from ..care_decisioning.pipeline import Pipeline
from ..config import Settings, get_settings
from ..member_record.mongo import MongoStore


def build_mongo_client(uri: str) -> Any:
    """Return a pymongo-compatible client. Uses mongomock when uri is memory://."""
    if uri.startswith("memory://"):
        import mongomock

        return mongomock.MongoClient()
    from pymongo import MongoClient

    return MongoClient(uri)


def build_store(settings: Settings) -> MongoStore:
    client = build_mongo_client(settings.mongo_uri)
    store = MongoStore(client, settings.mongo_db, settings.payer_org_id)
    store.ensure_indexes()
    return store


def build_pipeline(store: MongoStore) -> Pipeline:
    return Pipeline(store)


def get_store(request: Request) -> MongoStore:
    store = getattr(request.app.state, "store", None)
    if store is None:  # pragma: no cover - defensive
        store = build_store(get_settings())
        request.app.state.store = store
    return store


def get_pipeline(request: Request) -> Pipeline:
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:  # pragma: no cover - defensive
        pipeline = build_pipeline(get_store(request))
        request.app.state.pipeline = pipeline
    return pipeline


StoreDep = Depends(get_store)
PipelineDep = Depends(get_pipeline)
