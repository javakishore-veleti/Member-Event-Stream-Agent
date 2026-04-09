"""Concrete LlmClient backed by Google ADK's LlmAgent + Runner.

This module is the only place in the codebase that imports from the
``google`` namespace, and every google-adk import is deferred until
``GoogleAdkClient`` is constructed so the rest of the package — and the
unit suite — never need ``google-adk`` installed.

Architecture
------------
For each agent stage we own (triage / enrichment narrative / scoring /
recommendation) we instantiate one ``google.adk.agents.LlmAgent`` with a
stage-specific instruction. All four agents share a single
``InMemoryRunner`` and a single ``InMemorySessionService`` so calls are
cheap to dispatch and the cost of building runners is paid once per
process. Each ``complete_*`` call:

    1. Ensures the per-agent session exists (creates it lazily).
    2. Builds the user message as ``google.genai.types.Content`` carrying
       the prompt + a JSON-encoded context block + a strict-JSON
       instruction.
    3. Awaits ``Runner.run_async`` and reads the final response event.
    4. Strips any code fences, parses the JSON, and constructs the
       matching typed dataclass.

Failure modes — network errors, model refusals, malformed JSON — all
surface as exceptions; the calling AdkXxxAgent's existing fall-back path
catches them and runs its rule-based twin, exactly as it did against the
previous google-genai-only implementation.

Configure with:
    pip install ".[adk]"
    export GOOGLE_API_KEY=...     # or GEMINI_API_KEY
    export LLM_PROVIDER=google_adk
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from .llm import (
    NarrativeResponse,
    RecommendationResponse,
    ScoringResponse,
    TriageResponse,
)

DEFAULT_MODEL = "gemini-2.0-flash"
APP_NAME = "member_event_stream_agent"
USER_ID = "system"

_AGENT_INSTRUCTIONS: dict[str, str] = {
    "scoring": (
        "You are a healthcare risk-scoring assistant for a US health-plan "
        "payer. Given an inbound member event and the recent event history, "
        "return strict JSON with keys score (0..1 float), rationale (one "
        "sentence), and citations (list of event_id strings). Do not invent "
        "events. Do not include prose outside the JSON."
    ),
    "triage": (
        "You triage healthcare member events for a US health-plan payer. "
        "Given an event and recent history, choose at most one RiskDimension "
        "from: readmission, care_gap, adherence, polypharmacy, fwa, "
        "pa_decision. Return strict JSON with keys use_case (string or null) "
        "and rationale (string)."
    ),
    "narrative": (
        "You are a healthcare summarization assistant. Given a member's "
        "recent event timeline, write a single short paragraph summarizing "
        "the most clinically relevant signals. Do not invent events. Return "
        "strict JSON with one key: narrative (string)."
    ),
    "recommendation": (
        "You are a healthcare care-team routing assistant. Given a risk "
        "score, the use case it scored, and a short member narrative, "
        "choose exactly one action from: none, notify_care_manager, "
        "open_outreach, queue_pa_review, propose_intervention, "
        "escalate_fwa, draft_pa_response. Return strict JSON with keys "
        "action (string) and notes (string)."
    ),
}


class GoogleAdkClient:
    """LlmClient implementation backed by the full google-adk Runner stack.

    The constructor imports google-adk lazily so importing this module is
    always safe; only instantiation requires the optional ``[adk]`` extra.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        app_name: str = APP_NAME,
        user_id: str = USER_ID,
    ) -> None:
        try:
            from google.adk.agents import LlmAgent  # type: ignore[import-not-found]
            from google.adk.runners import InMemoryRunner  # type: ignore[import-not-found]
            from google.genai import types as genai_types  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - exercised at deploy time
            raise ImportError(
                'google-adk is not installed. Run `pip install ".[adk]"` '
                "to enable the GoogleAdkClient.",
            ) from exc

        # Some google-adk releases pick the API key out of the environment
        # rather than a constructor arg. Mirror it here so callers can pass
        # api_key= explicitly without forcing every deployment to also set
        # the env var by hand.
        if api_key:
            import os

            os.environ.setdefault("GOOGLE_API_KEY", api_key)
            os.environ.setdefault("GEMINI_API_KEY", api_key)

        self._LlmAgent = LlmAgent
        self._InMemoryRunner = InMemoryRunner
        self._types = genai_types
        self._model = model
        self._app_name = app_name
        self._user_id = user_id

        # One LlmAgent + Runner per stage. Sessions are created lazily.
        self._runners: dict[str, Any] = {}
        self._sessions: dict[str, str] = {}
        self._lock = asyncio.Lock()

        for kind, instruction in _AGENT_INSTRUCTIONS.items():
            agent = LlmAgent(
                name=f"mesa_{kind}",
                model=model,
                instruction=instruction,
            )
            self._runners[kind] = InMemoryRunner(agent=agent, app_name=app_name)

    # ------------------------------------------------------------------
    # LlmClient Protocol
    # ------------------------------------------------------------------

    async def complete_scoring(
        self,
        *,
        prompt: str,
        context: dict[str, Any],
    ) -> ScoringResponse:
        payload = await self._run_agent(
            kind="scoring", prompt=prompt, context=context,
        )
        return ScoringResponse(
            score=float(payload.get("score", 0.0)),
            rationale=str(payload.get("rationale", "")),
            citations=[str(c) for c in payload.get("citations", []) if c],
        )

    async def complete_triage(
        self,
        *,
        prompt: str,
        context: dict[str, Any],
    ) -> TriageResponse:
        payload = await self._run_agent(
            kind="triage", prompt=prompt, context=context,
        )
        use_case = payload.get("use_case")
        return TriageResponse(
            use_case=str(use_case) if use_case else None,
            rationale=str(payload.get("rationale", "")),
        )

    async def complete_narrative(
        self,
        *,
        prompt: str,
        context: dict[str, Any],
    ) -> NarrativeResponse:
        payload = await self._run_agent(
            kind="narrative", prompt=prompt, context=context,
        )
        return NarrativeResponse(narrative=str(payload.get("narrative", "")))

    async def complete_recommendation(
        self,
        *,
        prompt: str,
        context: dict[str, Any],
    ) -> RecommendationResponse:
        payload = await self._run_agent(
            kind="recommendation", prompt=prompt, context=context,
        )
        return RecommendationResponse(
            action=str(payload.get("action", "")),
            notes=str(payload.get("notes", "")),
        )

    # ------------------------------------------------------------------
    # ADK Runner plumbing
    # ------------------------------------------------------------------

    async def _ensure_session(self, kind: str) -> str:  # pragma: no cover - network
        async with self._lock:
            existing = self._sessions.get(kind)
            if existing is not None:
                return existing
            runner = self._runners[kind]
            session = await runner.session_service.create_session(
                app_name=self._app_name,
                user_id=self._user_id,
                session_id=f"{kind}-{uuid.uuid4()}",
            )
            self._sessions[kind] = session.id
            return session.id

    async def _run_agent(
        self,
        *,
        kind: str,
        prompt: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:  # pragma: no cover - network
        runner = self._runners[kind]
        session_id = await self._ensure_session(kind)

        full_prompt = (
            f"{prompt}\n\nCONTEXT (JSON):\n"
            f"{json.dumps(context, default=str)}\n\n"
            "Respond with strict JSON only — no prose, no code fences."
        )
        message = self._types.Content(
            role="user",
            parts=[self._types.Part(text=full_prompt)],
        )

        text_chunks: list[str] = []
        async for event in runner.run_async(
            user_id=self._user_id,
            session_id=session_id,
            new_message=message,
        ):
            if not event.is_final_response():
                continue
            content = getattr(event, "content", None)
            if content is None:
                continue
            for part in getattr(content, "parts", []) or []:
                text = getattr(part, "text", None)
                if text:
                    text_chunks.append(text)

        text = "".join(text_chunks).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"google_adk_client[{kind}]: non-JSON response: {text!r}",
            ) from exc
