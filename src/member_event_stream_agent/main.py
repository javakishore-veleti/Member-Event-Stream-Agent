"""Process entrypoint.

For now this only stands up the FastAPI app with a health endpoint so the
existing CI smoke test continues to pass while later blocks of the dev plan
fill in the worker, agent pipeline, MCP gateway, and storage wiring.
"""
from __future__ import annotations

from fastapi import FastAPI

from . import __version__
from .config import get_settings
from .logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(title="member-event-stream-agent", version=__version__)

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/version")
    def version() -> dict[str, str]:
        return {"version": __version__}

    return application


app = create_app()
