from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated server-side configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AGENT_HUB_",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: PostgresDsn = PostgresDsn(
        "postgresql://agent_hub:agent_hub@localhost:5432/agent_hub"
    )
    database_connect_timeout_seconds: int = Field(default=2, ge=1, le=30)


@lru_cache
def get_settings() -> Settings:
    return Settings()
