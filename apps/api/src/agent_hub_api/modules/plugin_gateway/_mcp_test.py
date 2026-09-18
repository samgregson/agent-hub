import socket
from dataclasses import dataclass

import pytest

from agent_hub_api.modules.plugin_gateway import (
    McpPluginClient,
    PluginEndpointRejected,
    PluginTransportError,
    _mcp,
)


@dataclass
class FakeContent:
    text: str


@dataclass
class FakeResponse:
    content: list[FakeContent]
    structured_content: dict[str, object] | None
    is_error: bool = False


class FakeClient:
    response = FakeResponse(
        content=[FakeContent("Fixture available")],
        structured_content={"status": "available"},
    )
    calls: list[tuple[str, dict[str, object], float | None]] = []

    def __init__(self, endpoint: str, *, read_timeout_seconds: float) -> None:
        self.endpoint = endpoint
        self.read_timeout_seconds = read_timeout_seconds

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        read_timeout_seconds: float | None,
    ) -> FakeResponse:
        self.calls.append((name, arguments, read_timeout_seconds))
        return self.response


@pytest.mark.asyncio
async def test_mcp_client_normalizes_a_bounded_result(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeClient.calls = []
    monkeypatch.setattr(_mcp, "Client", FakeClient)
    client = McpPluginClient(
        endpoint="http://foundation-fixture:8000/mcp",
        timeout_seconds=12,
        max_result_bytes=1_024,
        allow_private_network=True,
    )

    result = await client.call_tool("foundation_status", {})

    assert FakeClient.calls == [("foundation_status", {}, 12)]
    assert result.content == ("Fixture available",)
    assert result.structured_content == {"status": "available"}


@pytest.mark.asyncio
async def test_mcp_client_rejects_an_oversized_result(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeClient.response = FakeResponse(
        content=[FakeContent("x" * 100)],
        structured_content=None,
    )
    monkeypatch.setattr(_mcp, "Client", FakeClient)
    client = McpPluginClient(
        endpoint="http://foundation-fixture:8000/mcp",
        timeout_seconds=12,
        max_result_bytes=32,
        allow_private_network=True,
    )

    with pytest.raises(PluginTransportError, match="size limit"):
        await client.call_tool("foundation_status", {})


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://plugin.example/mcp",
        "https://user:password@plugin.example/mcp",
        "https://plugin.example/mcp?token=secret",
        "https://plugin.example/mcp#fragment",
        "http://127.0.0.1/mcp",
    ],
)
def test_mcp_client_rejects_unsafe_endpoint(endpoint: str) -> None:
    client = McpPluginClient(
        endpoint=endpoint,
        timeout_seconds=12,
        max_result_bytes=1_024,
    )

    with pytest.raises(PluginEndpointRejected):
        client._validate_endpoint()


def test_internal_fixture_endpoint_requires_an_explicit_catalog_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def should_not_resolve(*_: object, **__: object) -> None:
        raise AssertionError("private-network exception must not resolve the endpoint")

    monkeypatch.setattr(socket, "getaddrinfo", should_not_resolve)
    client = McpPluginClient(
        endpoint="http://foundation-fixture:8000/mcp",
        timeout_seconds=12,
        max_result_bytes=1_024,
        allow_private_network=True,
    )

    client._validate_endpoint()
