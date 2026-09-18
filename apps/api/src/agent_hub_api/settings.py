from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, PostgresDsn, SecretStr, field_validator, model_validator
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
    identity_mode: Literal["fixed", "trusted_header"] = "fixed"
    fixed_identity_subject: str = Field(default="local-user", min_length=1, max_length=240)
    trusted_identity_header: str = Field(
        default="X-Agent-Hub-Subject", min_length=1, max_length=120
    )
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("AGENT_HUB_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    openai_model: str = Field(default="gpt-5.1", min_length=1, max_length=120)
    agent_recursion_limit: int = Field(default=100, ge=10, le=1000)
    enable_foundation_test_tool: bool = False
    project_file_max_bytes: int = Field(default=1_000_000, ge=1_024, le=20_000_000)
    project_file_max_files: int = Field(default=1_000, ge=1, le=100_000)
    project_file_search_max_matches: int = Field(default=200, ge=1, le=10_000)
    plugin_tool_timeout_seconds: float = Field(default=30, ge=1, le=300)
    plugin_result_max_bytes: int = Field(default=1_000_000, ge=1_024, le=20_000_000)
    plugin_discovery_cache_seconds: float = Field(default=300, ge=1, le=3600)

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def normalize_blank_openai_key(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def require_trusted_identity_in_production(self) -> "Settings":
        if self.environment == "production" and self.identity_mode != "trusted_header":
            raise ValueError("production requires identity_mode='trusted_header'")
        if self.environment == "production" and self.enable_foundation_test_tool:
            raise ValueError("the foundation test tool cannot be enabled in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
