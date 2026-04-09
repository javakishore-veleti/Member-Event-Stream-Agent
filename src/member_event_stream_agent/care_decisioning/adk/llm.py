"""LlmClient seam for ADK-backed agents.

The Protocol below is the only thing the ADK agent variants depend on.
A production deployment plugs in a real google-adk wrapper; the test
suite plugs in FakeLlmClient with canned structured responses.

Why a structured response model: every ADK agent in this codebase needs
the same shape back from the LLM — a numeric score, a short rationale,
and a list of citation event_ids. Returning a typed object instead of a
free-form string keeps parsing in one place and gives the pipeline an
auditable record for the immutable CaseFile.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ScoringResponse:
    """Structured response every scoring-style ADK call must return."""

    score: float
    rationale: str
    citations: list[str] = field(default_factory=list)


@dataclass
class TriageResponse:
    """Structured response for use-case classification calls."""

    use_case: str | None  # member of RiskDimension, or None to skip
    rationale: str = ""


class LlmClient(Protocol):
    """Minimal LLM seam used by every ADK agent in this package.

    Implementations:
        - GoogleAdkClient (iteration 3): wraps google-adk.
        - FakeLlmClient (tests): returns whatever was queued.

    Async on purpose so the production wrapper can use the ADK async API
    without forcing every caller to spin up a thread.
    """

    async def complete_scoring(
        self,
        *,
        prompt: str,
        context: dict[str, Any],
    ) -> ScoringResponse: ...

    async def complete_triage(
        self,
        *,
        prompt: str,
        context: dict[str, Any],
    ) -> TriageResponse: ...


# ---------------------------------------------------------------------------
# Test double
# ---------------------------------------------------------------------------


class FakeLlmClient:
    """In-process LlmClient that hands back queued responses.

    Tests construct it with a list of ScoringResponse / TriageResponse
    instances and (optionally) flag the next call to raise — the agent
    fall-back path is exercised that way.
    """

    def __init__(
        self,
        *,
        scoring_responses: list[ScoringResponse] | None = None,
        triage_responses: list[TriageResponse] | None = None,
        raise_on_next: bool = False,
    ) -> None:
        self._scoring = list(scoring_responses or [])
        self._triage = list(triage_responses or [])
        self._raise_on_next = raise_on_next
        self.scoring_calls: list[dict[str, Any]] = []
        self.triage_calls: list[dict[str, Any]] = []

    async def complete_scoring(
        self,
        *,
        prompt: str,
        context: dict[str, Any],
    ) -> ScoringResponse:
        self.scoring_calls.append({"prompt": prompt, "context": context})
        if self._raise_on_next:
            self._raise_on_next = False
            raise RuntimeError("simulated LLM failure")
        if not self._scoring:
            raise RuntimeError("FakeLlmClient: no scoring response queued")
        return self._scoring.pop(0)

    async def complete_triage(
        self,
        *,
        prompt: str,
        context: dict[str, Any],
    ) -> TriageResponse:
        self.triage_calls.append({"prompt": prompt, "context": context})
        if self._raise_on_next:
            self._raise_on_next = False
            raise RuntimeError("simulated LLM failure")
        if not self._triage:
            raise RuntimeError("FakeLlmClient: no triage response queued")
        return self._triage.pop(0)
