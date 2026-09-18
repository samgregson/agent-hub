import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from mcp import Client

from agent_hub_api.modules.plugin_gateway._application import PluginToolResult


class PluginTransportError(Exception):
    """The reviewed Plugin did not return a usable MCP result."""


@dataclass(frozen=True, slots=True)
class McpPluginClient:
    """One bounded Streamable HTTP call to a deployment-controlled Plugin endpoint."""

    endpoint: str
    timeout_seconds: float
    max_result_bytes: int

    async def call_tool(
        self, tool_name: str, arguments: Mapping[str, object]
    ) -> PluginToolResult:
        try:
            async with Client(self.endpoint, read_timeout_seconds=self.timeout_seconds) as client:
                response = await client.call_tool(
                    tool_name,
                    dict(arguments),
                    read_timeout_seconds=self.timeout_seconds,
                )
        except Exception as error:
            raise PluginTransportError(
                "The Plugin server is unavailable or did not respond."
            ) from error

        if response.is_error:
            raise PluginTransportError("The Plugin rejected the tool call.")

        content = tuple(_content_text(item) for item in response.content)
        structured_content = _structured_content(response.structured_content)
        serialized_size = len(
            json.dumps(
                {"content": content, "structuredContent": structured_content},
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if serialized_size > self.max_result_bytes:
            raise PluginTransportError("The Plugin result exceeded the configured size limit.")
        return PluginToolResult(content=content, structured_content=structured_content)


def _content_text(item: object) -> str:
    text = getattr(item, "text", None)
    if isinstance(text, str):
        return text
    try:
        return json.dumps(_json_value(item), separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise PluginTransportError("The Plugin returned unsupported MCP content.") from error


def _structured_content(value: object) -> Mapping[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise PluginTransportError("The Plugin returned malformed structured content.")
    return dict(value)


def _json_value(value: object) -> Any:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return value
