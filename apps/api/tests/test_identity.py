import pytest
from fastapi import Request
from pydantic import ValidationError

from agent_hub_api.modules.identity import IdentityUnavailable, create_identity_module
from agent_hub_api.settings import Settings


def request_with_headers(headers: list[tuple[bytes, bytes]]) -> Request:
    return Request({"type": "http", "headers": headers})


def test_fixed_identity_ignores_forged_browser_header() -> None:
    identity = create_identity_module(
        Settings(environment="test", fixed_identity_subject="trusted-local-user")
    )

    context = identity.resolve(request_with_headers([(b"x-agent-hub-subject", b"forged-user")]))

    assert context.subject == "trusted-local-user"


def test_trusted_header_identity_requires_platform_subject() -> None:
    identity = create_identity_module(Settings(environment="test", identity_mode="trusted_header"))

    with pytest.raises(IdentityUnavailable):
        identity.resolve(request_with_headers([]))


def test_trusted_header_identity_reads_configured_header() -> None:
    identity = create_identity_module(
        Settings(
            environment="test",
            identity_mode="trusted_header",
            trusted_identity_header="X-Platform-Subject",
        )
    )

    context = identity.resolve(request_with_headers([(b"x-platform-subject", b"platform-user")]))

    assert context.subject == "platform-user"


def test_production_rejects_fixed_identity() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", identity_mode="fixed")
