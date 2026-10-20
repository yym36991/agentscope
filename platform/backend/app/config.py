# -*- coding: utf-8 -*-
"""Platform backend configuration.

All values can be overridden via environment variables prefixed with
``PLATFORM_`` or a local ``.env`` file (see ``.env.example``).
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PLATFORM_",
        extra="ignore",
    )

    # Business database. The AgentScope runtime keeps its own database
    # ("agentscope"); the two never share tables (architecture.md §10.5).
    database_url: str = (
        "postgresql+asyncpg://postgres@localhost:5432/platform"
    )

    # JWT signing for the platform's own auth. The runtime's temporary
    # X-User-ID header is not used for platform end users (§8.2: the
    # runtime only ever sees the single principal sys:runtime).
    jwt_secret: str = "dev-only-jwt-secret"
    jwt_expire_minutes: int = 12 * 60

    # AgentScope runtime access. app/runtime_client is the only code
    # allowed to use these (§8.7 anti-corruption layer).
    runtime_base_url: str = "http://localhost:8000"
    runtime_principal: str = "sys:runtime"
    # Chat model the platform binds onto every stage session (§8.6:
    # the credential lives under sys:runtime, end users stay zero-config).
    runtime_model: str = "glm-5.3"

    # Where stage artifacts (PRD, prototypes...) are stored on disk.
    artifact_dir: str = str(
        Path(__file__).resolve().parents[1] / "artifacts"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
