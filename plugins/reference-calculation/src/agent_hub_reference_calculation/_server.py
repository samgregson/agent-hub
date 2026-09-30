from pathlib import Path

from fastmcp import FastMCP
from fastmcp.apps import AppConfig, app_config_to_meta_dict

CANTILEVER_TIP_LOAD_TOOL_NAME = "calculate_cantilever_tip_load"
CALCULATION_APP_RESOURCE_URI = "ui://agent-hub-reference-calculation/cantilever.html"
_APP_PATH = Path(__file__).parents[2] / "app" / "cantilever-view.html"


def create_reference_calculation_server() -> FastMCP:
    """Create the portable calculation Plugin without starting a transport."""
    mcp = FastMCP("agent-hub-reference-calculation")

    @mcp.tool(name=CANTILEVER_TIP_LOAD_TOOL_NAME, annotations={"idempotentHint": True})
    async def calculate_cantilever_tip_load(length_m: float, tip_load_kn: float) -> dict[str, object]:
        """Calculate fixed-end moment for a cantilever with one tip point load.

        Inputs are documented in metres and kilonewtons. The result is a normal,
        structured invalid result when either quantity is non-positive.
        """
        validation = {"status": "valid", "warnings": []}
        if length_m <= 0 or tip_load_kn <= 0:
            warnings: list[str] = []
            if length_m <= 0:
                warnings.append("Length must be greater than zero metres.")
            if tip_load_kn <= 0:
                warnings.append("Tip load must be greater than zero kilonewtons.")
            validation = {"status": "invalid", "warnings": warnings}

        return {
            "calculation": {
                "kind": "cantileverTipLoad",
                "formula": "M_max = P × L",
                "length": {"value": float(length_m), "unit": "m"},
                "tipLoad": {"value": float(tip_load_kn), "unit": "kN"},
                "maximumMoment": {"value": float(tip_load_kn * length_m), "unit": "kN·m"},
            },
            "validation": validation,
        }

    @mcp.resource(
        uri=CALCULATION_APP_RESOURCE_URI,
        name="Cantilever moment view",
        description="An editable cantilever beam calculation view.",
        mime_type="text/html;profile=mcp-app",
        annotations={"readOnlyHint": True, "idempotentHint": True},
        meta={"ui": app_config_to_meta_dict(AppConfig())},
    )
    async def cantilever_view() -> str:
        return _APP_PATH.read_text(encoding="utf-8")

    return mcp


def main() -> None:
    create_reference_calculation_server().run(transport="http", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
