"""Centralized typed settings loaded from environment variables.

Every value the service consumes goes through this module. There must be no
os.getenv calls scattered across the codebase -- if you need a new setting,
add it here so it shows up in .env.example reviews.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings.

    Values are read from environment variables. In tests, a fixture overrides
    the Settings instance via dependency_overrides.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Runtime -----------------------------------------------------------
    environment: Literal["development", "staging", "production", "test"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # -- Database ----------------------------------------------------------
    database_url: PostgresDsn = Field(
        default="postgresql+psycopg://zapagent:zapagent_local_dev@postgres:5432/zapagent"
    )
    database_url_sync: str = (
        "postgresql://zapagent:zapagent_local_dev@postgres:5432/zapagent"
    )

    # -- Supabase ----------------------------------------------------------
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    # -- Redis / Celery ----------------------------------------------------
    redis_url: RedisDsn = Field(default="redis://redis:6379/0")
    celery_broker_url: RedisDsn = Field(default="redis://redis:6379/1")
    celery_result_backend: RedisDsn = Field(default="redis://redis:6379/2")

    # -- Anthropic (Claude Haiku) -----------------------------------------
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"
    anthropic_max_tokens: int = 1024

    # -- Voyage AI (embeddings) -------------------------------------------
    voyage_api_key: str = ""
    voyage_model: str = "voyage-3-lite"

    # -- Evolution API ----------------------------------------------------
    evolution_api_url: str = "http://evolution:8080"
    evolution_api_key: str = ""
    evolution_webhook_secret: str = ""

    # -- Google Calendar --------------------------------------------------
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = ""

    # -- Asaas ------------------------------------------------------------
    asaas_api_key: str = ""
    asaas_base_url: str = "https://sandbox.asaas.com/api/v3"
    asaas_webhook_token: str = ""

    # -- Agent behavior ---------------------------------------------------
    agent_confidence_threshold: float = 0.65
    agent_response_max_chars: int = 1500
    agent_rag_top_k: int = 4

    # -- Observability ----------------------------------------------------
    sentry_dsn: str = ""
    otel_exporter_otlp_endpoint: str = ""

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_test(self) -> bool:
        return self.environment == "test"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton settings instance. Cached for the process lifetime."""
    return Settings()  # type: ignore[call-arg]
