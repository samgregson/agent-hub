from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from agent_hub_api.settings import Settings


class IdentityUnavailable(Exception):
    """The hosting platform did not supply an authenticated subject."""


@dataclass(frozen=True, slots=True)
class RequestContext:
    subject: str
    request_id: str


@dataclass(frozen=True, slots=True)
class IdentityEvidence:
    """Trusted transport evidence presented to the Identity Module."""

    headers: Mapping[str, str]

    def header(self, name: str) -> str:
        expected = name.casefold()
        return next(
            (value for key, value in self.headers.items() if key.casefold() == expected), ""
        )


class IdentityAdapter(Protocol):
    def resolve_subject(self, evidence: IdentityEvidence) -> str: ...


class IdentityModule:
    """Resolve trusted hosting identity into application request context."""

    def __init__(self, adapter: IdentityAdapter) -> None:
        self._adapter = adapter

    def resolve(self, evidence: IdentityEvidence) -> RequestContext:
        return RequestContext(
            subject=self._adapter.resolve_subject(evidence),
            request_id=str(uuid4()),
        )


class FixedIdentityAdapter:
    def __init__(self, subject: str) -> None:
        self._subject = subject

    def resolve_subject(self, evidence: IdentityEvidence) -> str:
        del evidence
        return self._subject


class TrustedHeaderIdentityAdapter:
    def __init__(self, header_name: str) -> None:
        self._header_name = header_name

    def resolve_subject(self, evidence: IdentityEvidence) -> str:
        subject = evidence.header(self._header_name).strip()
        if not subject or len(subject) > 240:
            raise IdentityUnavailable
        return subject


def create_identity_module(settings: Settings) -> IdentityModule:
    if settings.identity_mode == "trusted_header":
        return IdentityModule(TrustedHeaderIdentityAdapter(settings.trusted_identity_header))
    return IdentityModule(FixedIdentityAdapter(settings.fixed_identity_subject))
