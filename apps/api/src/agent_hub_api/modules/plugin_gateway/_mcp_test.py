from dataclasses import dataclass

import pytest

from agent_hub_api.modules.plugin_gateway import McpPluginClient, PluginTransportError, _mcp


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
    )

    with pytest.raises(PluginTransportError, match="size limit"):
        await client.call_tool("foundation_status", {})
