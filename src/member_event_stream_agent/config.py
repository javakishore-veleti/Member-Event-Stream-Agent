"""Environment-driven settings for member_event_stream_agent.

All runtime configuration funnels through Settings so the rest of the codebase
never reads os.environ directly. Backed by pydantic-settings, which loads from
process env and an optional .env file at the repo root.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mongo_uri: str = Field(default="memory://", alias="MONGO_URI")
    mongo_db: str = Field(default="mesa", alias="MONGO_DB")
    payer_org_id: str = Field(default="dev-payer", alias="PAYER_ORG_ID")

    kafka_brokers: str = Field(default="memory://", alias="KAFKA_BROKERS")
    kafka_topic: str = Field(default="member.events", alias="KAFKA_TOPIC")

    llm_api_key: str = Field(default="", alias="LLM_API_KEY")

    mcp_token: str = Field(default="dev-token", alias="MCP_TOKEN")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor so Settings is constructed exactly once per process."""
    return Settings()
