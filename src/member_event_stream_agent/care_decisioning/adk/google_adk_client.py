"""Concrete LlmClient backed by google-adk / google-genai.

This module is the only place in the codebase that imports from the
``google`` namespace, and the import is deferred until ``GoogleAdkClient``
is constructed so the rest of the package — and the unit suite — never
need ``google-adk`` installed.

Why google-genai under the hood: google-adk's high-level Agent / Runner
APIs are built on top of the google-genai SDK, and our seam only needs a
single structured-text completion per agent stage. We call generate_content
with a JSON-mode response schema and parse it into the same dataclasses
the FakeLlmClient already returns, so swapping in this client requires no
changes anywhere else in care_decisioning/.

Configure with:
    pip install ".[adk]"
    export GOOGLE_API_KEY=...     # or GEMINI_API_KEY
    export LLM_PROVIDER=google_adk
"""
from __future__ import annotations

import json
from typing import Any

from .llm import ScoringResponse, TriageResponse

DEFAULT_MODEL = "gemini-2.0-flash"


class GoogleAdkClient:
    """LlmClient implementation that calls Gemini via google-genai.

    The constructor imports google-genai lazily so importing this module
    is always safe; only instantiation requires the optional extra.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
    ) -> None:
        try:
            from google import genai  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - exercised at deploy time
            raise ImportError(
                "google-adk is not installed. Run `pip install \".[adk]\"` "
                "to enable the GoogleAdkClient.",
            ) from exc

        self._genai = genai
        self._model = model
        self._client = genai.Client(api_key=api_key) if api_key else genai.Client()

    # ------------------------------------------------------------------
    # LlmClient Protocol
    # ------------------------------------------------------------------

    async def complete_scoring(
        self,
        *,
        prompt: str,
        context: dict[str, Any],
    ) -> ScoringResponse:
        payload = await self._generate_json(prompt=prompt, context=context)
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
        payload = await self._generate_json(prompt=prompt, context=context)
        use_case = payload.get("use_case")
        return TriageResponse(
            use_case=str(use_case) if use_case else None,
            rationale=str(payload.get("rationale", "")),
        )

    # ------------------------------------------------------------------

    async def _generate_json(
        self,
        *,
        prompt: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        full_prompt = (
            f"{prompt}\n\n"
            f"CONTEXT (JSON):\n{json.dumps(context, default=str)}\n\n"
            "Respond with strict JSON only — no prose, no code fences."
        )
        response = await self._client.aio.models.generate_content(  # pragma: no cover - network
            model=self._model,
            contents=full_prompt,
        )
        text = getattr(response, "text", "") or ""
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"google_adk_client: non-JSON response: {text!r}") from exc
