# Google ADK Integration Plan

Tracks the conversion of `care_decisioning/` from rule-based stubs to
Google Agent Development Kit (ADK) backed agents. Updated as each task
lands so the README serves as a live status board for this iteration.

## Design seams already in place

- `care_decisioning/base.py` — `Agent` Protocol with `async def run(ctx)`. Every
  built-in agent already conforms, so swapping any one out for an ADK-backed
  implementation requires no caller-side change.
- `care_decisioning/pipeline.py` — owns the order of stages and the storage
  writes. The pipeline does not care whether a stage is rule-based or LLM-backed.
- `care_decisioning/scoring.py` — already has a `TODO(adk)` marker per scorer
  method. Each one returns the same `(score, rationale, citations)` tuple the
  ADK variant must produce.

## Why an LlmClient protocol layer

`google-adk` is an optional runtime dependency (Gemini API key required, network
access required). The unit suite must stay offline. We introduce a thin
`LlmClient` Protocol inside `care_decisioning/adk/` so:

1. Production code calls `LlmClient.complete(...)` and parses a structured
   response. The real implementation wraps a Google ADK runner.
2. Tests inject a `FakeLlmClient` that returns canned structured responses.
3. The optional extra `pip install .[adk]` pulls in `google-adk` and friends.
   The base install stays slim and the test suite stays offline.

## Status board

Legend: `[ ]` not started  ·  `[~]` in progress  ·  `[x]` done

### Iteration 1 — Seam + first agent

- [x] T1.1  `README_ADK_Plan.md` (this doc) created and committed.
- [x] T1.2  `pyproject.toml` declares optional `[adk]` extra.
- [x] T1.3  `care_decisioning/adk/__init__.py` package created.
- [x] T1.4  `care_decisioning/adk/llm.py` — `LlmClient` Protocol +
            `FakeLlmClient` for tests + `ScoringResponse` dataclass.
- [x] T1.5  `care_decisioning/adk/scoring_adk.py` — `AdkScoringAgent` that
            wraps an `LlmClient`, prompts it with the grounded Member 360
            context, parses a `ScoringResponse`, falls back to the rule-based
            scorer on failure.
- [x] T1.6  `tests/care_decisioning/test_scoring_adk.py` — `FakeLlmClient`
            round-trip plus a fall-back test that simulates an LLM error and
            asserts the rule-based path runs.
- [x] T1.7  Pipeline knob: `Pipeline(..., scoring_agent=...)` lets a deployment
            pick the ADK variant without touching the pipeline source.

### Iteration 2 — Second agent (Triage)

- [x] T2.1  `care_decisioning/adk/triage_adk.py` — `AdkTriageAgent` that asks
            the LLM to classify (event family, kind, recent context) into one
            of the supported `RiskDimension` values.
- [x] T2.2  `tests/care_decisioning/test_triage_adk.py` — fake-LLM round trip,
            unknown use_case → skip, and LLM-error fall-back to rule-based.
- [x] T2.3  `Pipeline` accepts an optional `triage_agent` knob, mirroring T1.7.
            (Landed alongside the scoring knob in iteration 1.)

### Iteration 3 — Real google-adk wiring

- [x] T3.1  `care_decisioning/adk/google_adk_client.py` — concrete
            `LlmClient` wrapping google-genai (the SDK ADK is built on).
            Module imports cleanly without `google-adk`; the
            `from google import genai` line is deferred to `__init__` and
            raises a `pip install ".[adk]"` ImportError if the extra is
            missing.
- [x] T3.2  `care_decisioning/adk/factory.py` selects the client from
            `Settings.LLM_PROVIDER` (default `stub`). `LLM_MODEL` overrides
            the Gemini model. Unknown providers raise immediately so a
            misconfigured deploy fails fast instead of silently stubbing.
- [x] T3.3  `README_HealthCare.md` "LLM provider selection" section
            documents the two providers, the env vars, and the
            fall-back-on-error contract every ADK agent honors.

### Iteration 4 — Remaining agents

- [x] T4.1  `AdkEnrichmentAgent` runs the rule-based DB read first (the LLM
            never invents rows) and then asks the LLM for a one-paragraph
            narrative attached to the new `PipelineCtx.narrative` field. The
            scorer + recommender lean on it.
- [x] T4.2  `AdkRecommendationAgent` asks the LLM to pick a `DispositionAction`
            given the score, use case, and narrative. Coerces to the enum and
            falls back to the rule ladder on LLM error or unknown action.
- [x] T4.3  TODO(adk) docstring stripped from `scoring.py`; the rule-based
            scorer is now formally documented as the deterministic fall-back
            twin to `AdkScoringAgent`.

## Wrap-up

Conversion complete: every stage in `care_decisioning/` has both a
deterministic rule-based implementation and an ADK-backed variant that
shares the same `Agent` Protocol. Pipeline accepts knobs for all four
stages. The whole thing degrades cleanly to rule-based when the LLM is
unreachable or `LLM_PROVIDER=stub`. Full suite at 68 passing.

### Iteration 5 — Full LlmAgent + Runner orchestration

- [x] T5.1  `GoogleAdkClient` upgraded from raw `google.genai` to the full
            `google.adk.agents.LlmAgent` + `google.adk.runners.InMemoryRunner`
            stack. One LlmAgent per stage (scoring / triage / narrative /
            recommendation), each with its own stage instruction. Sessions
            are created lazily per stage and cached for the lifetime of the
            client.
- [x] T5.2  Public seam unchanged: the four `complete_*` methods still
            return the same `ScoringResponse` / `TriageResponse` /
            `NarrativeResponse` / `RecommendationResponse` dataclasses, so
            none of the AdkXxxAgent variants needed any code changes.
            Their fall-back-on-error contracts continue to apply.
- [x] T5.3  Test guard updated: `test_adk_factory.py` now checks for
            `google.adk` (not `google.genai`) when deciding whether to
            actually construct a real client, and asserts the import-error
            path still points the user at `pip install ".[adk]"`.

## Out of scope for this initiative

- Replacing `MongoStore` reads inside `EnrichmentAgent` with vector retrieval.
- Multi-model fallbacks (Gemini → Anthropic → OpenAI).
- Streaming tool-call style ADK interactions; the first cut uses one-shot
  structured completions.
