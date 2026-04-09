"""Tests for the LlmClient factory + the GoogleAdkClient import guard.

The factory is the only knob production cares about. We verify three
states the deployment can land in:

    1. LLM_PROVIDER=stub        -> FakeLlmClient (default; offline-safe)
    2. LLM_PROVIDER=google_adk  -> GoogleAdkClient *if* google-genai is
                                   installed, otherwise a clear ImportError
                                   so a misconfigured deploy fails fast.
    3. LLM_PROVIDER=garbage     -> ValueError, never silently falls back.
"""
from __future__ import annotations

import importlib
import sys

import pytest

from member_event_stream_agent.care_decisioning.adk.factory import build_llm_client
from member_event_stream_agent.care_decisioning.adk.llm import FakeLlmClient
from member_event_stream_agent.config import Settings


def test_factory_default_returns_stub() -> None:
    client = build_llm_client(Settings(LLM_PROVIDER="stub"))
    assert isinstance(client, FakeLlmClient)


def test_factory_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="unknown LLM_PROVIDER"):
        build_llm_client(Settings(LLM_PROVIDER="not-real"))


def test_factory_google_adk_path() -> None:
    """Either constructs the real client (when google-adk is installed) or
    raises an ImportError pointing the user at `pip install ".[adk]"`."""
    try:
        have_adk = (
            importlib.util.find_spec("google.adk") is not None
            and importlib.util.find_spec("google.genai") is not None
        )
    except (ModuleNotFoundError, ValueError):
        have_adk = False
    if have_adk:
        client = build_llm_client(Settings(LLM_PROVIDER="google_adk", LLM_API_KEY="dummy"))
        assert client is not None
    else:
        with pytest.raises(ImportError, match=r"pip install"):
            build_llm_client(Settings(LLM_PROVIDER="google_adk"))


def test_google_adk_client_module_imports_without_adk() -> None:
    """Importing the module itself must never require google-adk — only
    instantiating GoogleAdkClient does. This guarantees the rest of
    care_decisioning can keep importing the package."""
    sys.modules.pop(
        "member_event_stream_agent.care_decisioning.adk.google_adk_client",
        None,
    )
    module = importlib.import_module(
        "member_event_stream_agent.care_decisioning.adk.google_adk_client",
    )
    assert hasattr(module, "GoogleAdkClient")
