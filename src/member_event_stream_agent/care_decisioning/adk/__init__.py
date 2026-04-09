"""Google ADK-backed agent variants for care_decisioning.

The submodules in this package are LLM-backed implementations of the
Agent Protocol defined in care_decisioning.base. They live behind a thin
LlmClient seam (see llm.py) so:

    1. Production code can swap an ADK runner in with one constructor
       argument on Pipeline; nothing else changes.
    2. The unit suite can inject a FakeLlmClient and stay offline.
    3. google-adk itself is an optional dependency; only the concrete
       google_adk_client module imports it, and only when the [adk] extra
       is installed.
"""
