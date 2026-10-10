from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP
from fastmcp.apps import AppConfig, app_config_to_meta_dict

FIXTURE_TOOL_NAME = "foundation_status"
FIXTURE_APP_RESOURCE_URI = "ui://agent-hub-foundation/status.html"
FIXTURE_APP_MIME_TYPE = "text/html;profile=mcp-app"
FIXTURE_ARTIFACT_TYPE = "agent-hub.fixture.status"
_APP_PATH = Path(__file__).parents[2] / "app" / "foundation-status-view.html"


def _validate_document(document: dict[str, Any]) -> dict[str, Any]:
    artifact = document.get("artifact")
    payload = document.get("payload")
    if not isinstance(artifact, dict) or not isinstance(payload, dict):
        raise TypeError("Expected a complete portable Artifact Document")
    if artifact.get("type") != FIXTURE_ARTIFACT_TYPE:
        raise ValueError("The Artifact type is not supported by this Plugin")
    if artifact.get("schema") != {"id": FIXTURE_ARTIFACT_TYPE, "version": "1.0"}:
        raise ValueError("The Artifact schema is not supported by this Plugin")
    if payload.get("status") not in ("available", "unavailable"):
        raise ValueError("The status must be available or unavailable")
    return payload


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
        name="render_template_value",
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    async def render_template_value(template: str, value: float) -> dict[str, str]:
        """Replace a value marker in text; the Plugin owns this example operation."""
        return {"rendered": template.replace("{{value}}", str(value))}

    @mcp.tool(name="create_status_artifact")
    async def create_status_artifact(title: str) -> dict[str, Any]:
        """Create a portable status Artifact draft; the client owns persistence."""
        title = title.strip()
        if not title or len(title) > 120:
            raise ValueError("Title must contain 1 to 120 characters")
        return {
            "type": FIXTURE_ARTIFACT_TYPE,
            "title": title,
            "summary": "Fixture status is available.",
            "schema": {"id": FIXTURE_ARTIFACT_TYPE, "version": "1.0"},
            "payload": {"status": "available"},
        }

    @mcp.tool(name="validate_status_artifact", annotations={"readOnlyHint": True})
    async def validate_status_artifact(document: dict[str, Any]) -> dict[str, Any]:
        """Validate a complete inline status Artifact without host storage."""
        payload = _validate_document(document)
        return {"valid": True, "status": payload["status"]}

    @mcp.tool(name="set_status_artifact_status")
    async def set_status_artifact_status(
        document: dict[str, Any], status: Literal["available", "unavailable"]
    ) -> dict[str, Any]:
        """Return a complete replacement for an inline status Artifact."""
        _validate_document(document)
        replacement = deepcopy(document)
        replacement["payload"]["status"] = status
        replacement["artifact"]["summary"] = f"Fixture status is {status}."
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


def main() -> None:
    create_fixture_server().run(transport="http", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    create_fixture_server().run()
