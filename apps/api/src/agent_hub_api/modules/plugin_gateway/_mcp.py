import ipaddress
import json
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from mcp import Client

from agent_hub_api.modules.plugin_gateway._application import (
    PluginDiscoveredTool,
    PluginToolResult,
    PluginUiResource,
)

MCP_APP_MIME_TYPE = "text/html;profile=mcp-app"


class PluginTransportError(Exception):
    """The reviewed Plugin did not return a usable MCP result."""


class PluginEndpointRejected(PluginTransportError):
    """The deployment catalog endpoint violates outbound connection policy."""


@dataclass(frozen=True, slots=True)
class McpPluginClient:
    """One bounded Streamable HTTP call to a deployment-controlled Plugin endpoint."""

    endpoint: str
    timeout_seconds: float
    max_result_bytes: int
    allow_private_network: bool = False

    async def discover_tools(self) -> tuple[PluginDiscoveredTool, ...]:
        self._validate_endpoint()
        try:
            async with Client(self.endpoint, read_timeout_seconds=self.timeout_seconds) as client:
                result = await client.list_tools()
        except Exception as error:
            raise PluginTransportError(
                "The Plugin server is unavailable or did not respond."
            ) from error
        return tuple(
            PluginDiscoveredTool(
                name=tool.name,
                description=tool.description or "",
                read_only=bool(tool.annotations and tool.annotations.read_only_hint),
                input_schema=dict(tool.input_schema),
            )
            for tool in result.tools
        )

    async def call_tool(self, tool_name: str, arguments: Mapping[str, object]) -> PluginToolResult:
        self._validate_endpoint()
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

    async def read_ui_resource(self, resource_uri: str) -> PluginUiResource:
        """Read one declared HTML MCP App resource and reject all other payloads."""
        self._validate_endpoint()
        try:
            async with Client(self.endpoint, read_timeout_seconds=self.timeout_seconds) as client:
                resources = await client.list_resources()
                declared = next(
                    (resource for resource in resources.resources if resource.uri == resource_uri),
                    None,
                )
                if declared is None or declared.mime_type != MCP_APP_MIME_TYPE:
                    raise PluginTransportError(
                        "The Plugin did not declare a compatible App resource."
                    )
                response = await client.read_resource(resource_uri)
        except PluginTransportError:
            raise
        except Exception as error:
            raise PluginTransportError(
                "The Plugin App resource is unavailable or did not respond."
            ) from error

        if len(response.contents) != 1:
            raise PluginTransportError("The Plugin App resource returned an invalid response.")
        content = response.contents[0]
        html = getattr(content, "text", None)
        if (
            getattr(content, "uri", None) != resource_uri
            or getattr(content, "mime_type", None) not in {None, MCP_APP_MIME_TYPE}
            or not isinstance(html, str)
            or len(html.encode("utf-8")) > self.max_result_bytes
        ):
            raise PluginTransportError("The Plugin App resource is not safe HTML.")
        return PluginUiResource(uri=resource_uri, html=html)

    def _validate_endpoint(self) -> None:
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise PluginEndpointRejected("The configured Plugin endpoint is not a safe MCP URL.")
        if self.allow_private_network:
            return
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            resolved = socket.getaddrinfo(parsed.hostname, port)
        except (socket.gaierror, ValueError) as error:
            raise PluginEndpointRejected(
                "The configured Plugin hostname could not be resolved."
            ) from error
        addresses: set[str] = set()
        for entry in resolved:
            address = entry[4][0]
            if not isinstance(address, str):
                raise PluginEndpointRejected("The configured Plugin returned an invalid address.")
            addresses.add(address)
        if not addresses or any(_is_private_address(address) for address in addresses):
            raise PluginEndpointRejected(
                "The configured Plugin endpoint resolves to a private address."
            )


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


def _is_private_address(address: str) -> bool:
    try:
        candidate = ipaddress.ip_address(address)
    except ValueError as error:
        raise PluginEndpointRejected(
            "The configured Plugin returned an invalid address."
        ) from error
    return (
        candidate.is_private
        or candidate.is_loopback
        or candidate.is_link_local
        or candidate.is_reserved
        or candidate.is_unspecified
        or candidate.is_multicast
    )
