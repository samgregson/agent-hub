from pathlib import Path

from fastmcp import FastMCP
from fastmcp.apps import AppConfig, app_config_to_meta_dict

FIXTURE_TOOL_NAME = "foundation_status"
FIXTURE_APP_RESOURCE_URI = "ui://agent-hub-foundation/status.html"
FIXTURE_APP_MIME_TYPE = "text/html;profile=mcp-app"
_APP_PATH = Path(__file__).parents[2] / "app" / "foundation-status-view.html"


def create_fixture_server() -> FastMCP:
    """Create the fixture without starting a transport for conformance tests."""
    mcp = FastMCP("agent-hub-foundation-fixture")

    @mcp.tool(
        name=FIXTURE_TOOL_NAME,
        annotations={"readOnlyHint": True, "idempotentHint": True},
        app=AppConfig(resource_uri=FIXTURE_APP_RESOURCE_URI),
    )
    def foundation_status() -> dict[str, str]:
        """Return the portable fixture's small read-only status."""
        return {
            "status": "available",
            "source": "agent-hub-foundation-fixture",
        }

    @mcp.resource(
        uri=FIXTURE_APP_RESOURCE_URI,
        name="Foundation status view",
        description="A small standards-compatible MCP App for the fixture status.",
        mime_type=FIXTURE_APP_MIME_TYPE,
        annotations={"readOnlyHint": True, "idempotentHint": True},
        meta={"ui": app_config_to_meta_dict(AppConfig())},
    )
    def foundation_status_view() -> str:
        return _APP_PATH.read_text(encoding="utf-8")

    return mcp


def main() -> None:
    create_fixture_server().run(transport="http", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    create_fixture_server().run()
