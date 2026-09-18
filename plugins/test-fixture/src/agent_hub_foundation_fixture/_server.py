from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP
from fastmcp.apps import AppConfig, app_config_to_meta_dict

FIXTURE_TOOL_NAME = "foundation_status"
FIXTURE_CREATE_ARTIFACT_TOOL_NAME = "create_status_artifact"
FIXTURE_VALIDATE_ARTIFACT_TOOL_NAME = "validate_status_artifact"
FIXTURE_EDIT_ARTIFACT_TOOL_NAME = "set_status_artifact_status"
FIXTURE_APP_RESOURCE_URI = "ui://agent-hub-foundation/status.html"
FIXTURE_APP_MIME_TYPE = "text/html;profile=mcp-app"
_APP_PATH = Path(__file__).parents[2] / "app" / "foundation-status-view.html"
_ARTIFACT_TYPE = "agent-hub.fixture.status"
_ARTIFACT_SCHEMA = {"id": _ARTIFACT_TYPE, "version": "1.0"}
_PLUGIN_BINDING = {"id": "foundation-fixture", "version": "0.1.0"}


def create_fixture_server() -> FastMCP:
    """Create the fixture without starting a transport for conformance tests."""
    mcp = FastMCP("agent-hub-foundation-fixture")

    @mcp.tool(
        name=FIXTURE_TOOL_NAME,
        annotations={"readOnlyHint": True, "idempotentHint": True},
        app=AppConfig(resource_uri=FIXTURE_APP_RESOURCE_URI),
    )
    async def foundation_status() -> dict[str, str]:
        """Return the portable fixture's small read-only status."""
        return {
            "status": "available",
            "source": "agent-hub-foundation-fixture",
        }

    @mcp.tool(
        name=FIXTURE_CREATE_ARTIFACT_TOOL_NAME,
        annotations={"idempotentHint": True},
        app=AppConfig(resource_uri=FIXTURE_APP_RESOURCE_URI),
    )
    async def create_status_artifact(title: str) -> dict[str, object]:
        """Create a portable draft for a Foundation fixture status Artifact.

        The calling host assigns identity, Project placement, version, and
        provenance before persisting it. This server never stores Artifacts.
        """
        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("title must not be blank")
        return {
            "type": _ARTIFACT_TYPE,
            "title": normalized_title,
            "summary": "Foundation fixture status.",
            "schema": _ARTIFACT_SCHEMA,
            "payload": {"status": "available"},
        }

    @mcp.tool(
        name=FIXTURE_VALIDATE_ARTIFACT_TOOL_NAME,
        annotations={"readOnlyHint": True, "idempotentHint": True},
        app=AppConfig(resource_uri=FIXTURE_APP_RESOURCE_URI),
    )
    async def validate_status_artifact(document: dict[str, Any]) -> dict[str, Any]:
        """Validate and return a complete portable Foundation status Artifact document."""
        _validate_document(document)
        return document

    @mcp.tool(
        name=FIXTURE_EDIT_ARTIFACT_TOOL_NAME,
        annotations={"idempotentHint": True},
        app=AppConfig(resource_uri=FIXTURE_APP_RESOURCE_URI),
    )
    async def set_status_artifact_status(
        document: dict[str, Any], status: Literal["available", "unavailable"]
    ) -> dict[str, Any]:
        """Return a complete portable replacement with an updated fixture status."""
        _validate_document(document)
        replacement = deepcopy(document)
        replacement["payload"]["status"] = status
        return replacement

    @mcp.resource(
        uri=FIXTURE_APP_RESOURCE_URI,
        name="Foundation status view",
        description="A small standards-compatible MCP App for the fixture status.",
        mime_type=FIXTURE_APP_MIME_TYPE,
        annotations={"readOnlyHint": True, "idempotentHint": True},
        meta={"ui": app_config_to_meta_dict(AppConfig())},
    )
    async def foundation_status_view() -> str:
        return _APP_PATH.read_text(encoding="utf-8")

    return mcp


def _validate_document(document: dict[str, Any]) -> None:
    artifact = document.get("artifact")
    payload = document.get("payload")
    if not isinstance(artifact, dict) or not isinstance(payload, dict):
        raise TypeError("document must contain artifact and payload objects")
    if artifact.get("type") != _ARTIFACT_TYPE:
        raise ValueError("document has an unsupported Artifact type")
    if artifact.get("schema") != _ARTIFACT_SCHEMA:
        raise ValueError("document has an unsupported Artifact schema")
    if artifact.get("plugin") != _PLUGIN_BINDING:
        raise ValueError("document has an unsupported Plugin binding")
    if payload.get("status") not in {"available", "unavailable"}:
        raise ValueError("document payload has an unsupported status")


def main() -> None:
    create_fixture_server().run(transport="http", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    create_fixture_server().run()
