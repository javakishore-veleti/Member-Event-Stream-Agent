# Member-Event-Stream-Agent
A FastAPI service that consumes a stream of member events from Kafka, scores those events through a Google ADK multi-agent pipeline (Triage → Enrichment → Risk Scoring → Recommendation), persists state in MongoDB, and exposes investigative tools to LLM clients via a FastMCP server
