import pytest
from pydantic import ValidationError

from agent_hub_api.settings import Settings


def test_settings_reject_unknown_environment() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="staging")  # type: ignore[arg-type]


def test_settings_reject_non_postgres_database_url() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="https://example.com/database")  # type: ignore[arg-type]
