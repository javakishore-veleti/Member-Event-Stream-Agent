"""Factory that selects the LlmClient based on Settings.LLM_PROVIDER.

Returns FakeLlmClient when LLM_PROVIDER=stub (the default — keeps the suite
offline and lets local dev run end-to-end without an API key) and a real
GoogleAdkClient when LLM_PROVIDER=google_adk. Anything else raises so the
process fails fast at startup instead of falling through to a stub in
production by mistake.

A queued FakeLlmClient is also handy in CI: tests can build a stub with
canned responses and pass it directly to AdkScoringAgent / AdkTriageAgent
without going through the factory.
"""
from __future__ import annotations

from ...config import Settings, get_settings
from .llm import LlmClient, FakeLlmClient, ScoringResponse, TriageResponse


def _default_stub() -> FakeLlmClient:
    """A FakeLlmClient pre-loaded with neutral responses for local runs."""
    return FakeLlmClient(
        scoring_responses=[
            ScoringResponse(score=0.4, rationale="stub LLM neutral score", citations=[]),
        ]
        * 1024,
        triage_responses=[
            TriageResponse(use_case="care_gap", rationale="stub LLM default route"),
        ]
        * 1024,
    )


def build_llm_client(settings: Settings | None = None) -> LlmClient:
    settings = settings or get_settings()
    provider = (settings.llm_provider or "stub").strip().lower()
    if provider == "stub":
        return _default_stub()
    if provider == "google_adk":
        from .google_adk_client import GoogleAdkClient

        return GoogleAdkClient(
            model=settings.llm_model,
            api_key=settings.llm_api_key or None,
        )
    raise ValueError(
        f"unknown LLM_PROVIDER={settings.llm_provider!r}; expected stub|google_adk",
    )
