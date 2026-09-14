from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from fastapi import Request

from agent_hub_api.settings import Settings


class IdentityUnavailable(Exception):
    """The hosting platform did not supply an authenticated subject."""


@dataclass(frozen=True, slots=True)
class RequestContext:
    subject: str
    request_id: str


class IdentityAdapter(Protocol):
    def resolve_subject(self, request: Request) -> str: ...


class IdentityModule:
    """Resolve trusted hosting identity into application request context."""

    def __init__(self, adapter: IdentityAdapter) -> None:
        self._adapter = adapter

    def resolve(self, request: Request) -> RequestContext:
        return RequestContext(
            subject=self._adapter.resolve_subject(request),
            request_id=str(uuid4()),
        )


class FixedIdentityAdapter:
    def __init__(self, subject: str) -> None:
        self._subject = subject

    def resolve_subject(self, request: Request) -> str:
        del request
        return self._subject


class TrustedHeaderIdentityAdapter:
    def __init__(self, header_name: str) -> None:
        self._header_name = header_name

    def resolve_subject(self, request: Request) -> str:
        subject = request.headers.get(self._header_name, "").strip()
        if not subject or len(subject) > 240:
            raise IdentityUnavailable
        return subject


def create_identity_module(settings: Settings) -> IdentityModule:
    if settings.identity_mode == "trusted_header":
        return IdentityModule(TrustedHeaderIdentityAdapter(settings.trusted_identity_header))
    return IdentityModule(FixedIdentityAdapter(settings.fixed_identity_subject))
