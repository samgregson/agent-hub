import pytest
from pydantic import ValidationError

from agent_hub_api.settings import Settings


def test_settings_reject_unknown_environment() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="staging")  # type: ignore[arg-type]


def test_settings_reject_non_postgres_database_url() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="https://example.com/database")  # type: ignore[arg-type]


def test_production_requires_trusted_header_identity() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production")


def test_production_rejects_foundation_test_tool() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            identity_mode="trusted_header",
            enable_foundation_test_tool=True,
        )


def test_standard_openai_key_environment_name_is_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_HUB_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    settings = Settings()

    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "test-key"


def test_blank_openai_key_is_treated_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_HUB_OPENAI_API_KEY", "")

    assert Settings().openai_api_key is None
