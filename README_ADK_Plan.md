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

- [ ] T2.1  `care_decisioning/adk/triage_adk.py` — `AdkTriageAgent` that asks
            the LLM to classify (event family, kind, recent context) into one
            of the supported `RiskDimension` values.
- [ ] T2.2  `tests/care_decisioning/test_triage_adk.py` — fake-LLM round trip
            and skip-on-unknown-use-case.
- [ ] T2.3  `Pipeline` accepts an optional `triage_agent` knob, mirroring T1.7.

### Iteration 3 — Real google-adk wiring

- [ ] T3.1  `care_decisioning/adk/google_adk_client.py` — concrete
            `LlmClient` wrapping `google.adk` (only imported when the extra is
            installed; module guarded by ImportError).
- [ ] T3.2  Settings field `LLM_PROVIDER=stub|google_adk` selects the client
            at process startup; defaults to `stub` so existing tests stay
            offline-only.
- [ ] T3.3  Doc note in `README_HealthCare.md` calling out which stages are
            ADK-backed and what happens when the API key is missing.

### Iteration 4 — Remaining agents

- [ ] T4.1  `AdkEnrichmentAgent` (likely thin — enrichment is mostly DB reads,
            but the LLM can summarize the recent timeline into a paragraph the
            scorer can lean on).
- [ ] T4.2  `AdkRecommendationAgent` — convert the threshold ladder into a
            policy-aware LLM call that justifies the chosen action.
- [ ] T4.3  Rip the rule-based scorers' TODO(adk) markers once each agent has
            an ADK variant landed.

## Out of scope for this initiative

- Replacing `MongoStore` reads inside `EnrichmentAgent` with vector retrieval.
- Multi-model fallbacks (Gemini → Anthropic → OpenAI).
- Streaming tool-call style ADK interactions; the first cut uses one-shot
  structured completions.
