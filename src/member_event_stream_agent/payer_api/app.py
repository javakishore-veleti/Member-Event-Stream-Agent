"""FastAPI application factory.

Builds the FastAPI app, mounts /healthz and /version, attaches the read-side
member routes, and stashes the shared MongoStore + Pipeline on app.state so
dependency wiring in deps.py can hand them out per-request.

Construction is split into a factory so tests can build a fresh app per case
and inject their own MongoStore (e.g. one backed by mongomock with seed data).
"""
from __future__ import annotations

from fastapi import FastAPI

from .. import __version__
from ..care_decisioning.pipeline import Pipeline
from ..config import get_settings
from ..logging import configure_logging
from ..member_record.mongo import MongoStore
from .deps import build_pipeline, build_store
from .routes import router as members_router


def create_app(
    *,
    store: MongoStore | None = None,
    pipeline: Pipeline | None = None,
    lifespan: object | None = None,
) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title="member-event-stream-agent",
        version=__version__,
        lifespan=lifespan,  # type: ignore[arg-type]
    )

    if store is None:
        store = build_store(settings)
    if pipeline is None:
        pipeline = build_pipeline(store)

    application.state.store = store
    application.state.pipeline = pipeline
    application.state.settings = settings

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/version")
    def version() -> dict[str, str]:
        return {"version": __version__}

    application.include_router(members_router)

    return application
