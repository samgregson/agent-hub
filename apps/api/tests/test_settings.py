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
