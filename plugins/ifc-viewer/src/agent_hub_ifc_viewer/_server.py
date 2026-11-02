from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Annotated, Literal

import ifcopenshell
import ifcopenshell.util.element
from fastmcp import FastMCP
from fastmcp.apps import AppConfig, app_config_to_meta_dict
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
)

GUIDE_URI = "resource://agent-hub-ifc-viewer/agent-guide"
_GUIDE = Path(__file__).parents[2] / "AGENT_GUIDE.md"

APP_URI = "ui://agent-hub-ifc-viewer/view.html"
_APP = Path(__file__).parents[2] / "app" / "dist" / "index.html"
# Stay below the host's default structured-result budget, including JSON escaping.
MAX_IFC_BYTES = 400_000
MAX_RESULT_BYTES = 768_000
Scalar = StrictStr | StrictBool | StrictInt | StrictFloat | None


class ObjectMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    globalId: Annotated[str, Field(min_length=1, max_length=128)]
    values: dict[str, Scalar]


class IfcObjectRecord(BaseModel):
    globalId: str
    expressId: int
    ifcType: str
    name: str | None
    properties: dict[str, JsonValue]


class IfcObjects(BaseModel):
    kind: Literal["ifc.objects"]
    schemaVersion: Literal["1"]
    modelSha256: str
    ifcSchema: str
    objects: list[IfcObjectRecord]


class IfcView(BaseModel):
    kind: Literal["ifc.view"]
    schemaVersion: Literal["1"]
    ifcText: str
    modelSha256: str
    metadata: list[ObjectMetadata]
    colourBy: str | None


def _model(ifc_text: str):
    if not ifc_text.strip() or len(ifc_text.encode()) > MAX_IFC_BYTES:
        raise ToolError(f"IFC text must contain 1–{MAX_IFC_BYTES} UTF-8 bytes.")
    if not ifc_text.lstrip().startswith("ISO-10303-21;") or "END-ISO-10303-21;" not in ifc_text:
        raise ToolError("Expected a complete IFC STEP file.")
    try:
        model = ifcopenshell.file.from_string(ifc_text)
        products = model.by_type("IfcProduct")
        ids = [item.GlobalId for item in products]
        if len(ids) != len(set(ids)) or any(not value for value in ids):
            raise ValueError("Missing or duplicate GlobalIds")
        return model, products
    except Exception as error:
        raise ToolError(
            "Invalid or unsupported IFC file, or ambiguous object GlobalIds."
        ) from error


def _bounded(result: dict) -> ToolResult:
    try:
        size = len(json.dumps(result, ensure_ascii=True, allow_nan=False).encode())
    except (ValueError, TypeError, OverflowError) as error:
        raise ToolError("IFC properties and metadata must contain finite JSON values.") from error
    if size > MAX_RESULT_BYTES:
        raise ToolError("IFC result exceeds 768000 bytes; use a smaller model or property subset.")
    return ToolResult(
        content=f"Prepared {result['kind']} for model SHA-256 {result['modelSha256']}. "
        "Object records and metadata are available in the structured output.",
        structured_content=result,
    )


def create_ifc_viewer_server() -> FastMCP:
    mcp = FastMCP("agent-hub-ifc-viewer")

    @mcp.resource(uri=GUIDE_URI, name="IFC agent guide", mime_type="text/markdown")
    def agent_guide() -> str:
        return _GUIDE.read_text(encoding="utf-8")

    @mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True})
    def get_ifc_guide() -> ToolResult:
        """Read IFC usage instructions before inspecting, assigning metadata or composing calculations.

        Explains GlobalId joins, saved output recovery, file inputs, metadata assignment,
        colouring and Workflow bindings. Read-only; no Artifact or model mutation.
        """
        return ToolResult(content=agent_guide())

    @mcp.tool(
        annotations={"readOnlyHint": True, "idempotentHint": True},
        output_schema=IfcObjects.model_json_schema(),
    )
    def inspect_ifc_objects(ifc_text: str) -> ToolResult:
        """Read get_ifc_guide first. Extract IFC product records for Datasets, calculations and Workflow Map.

        Preserve globalId through calculations; join computed values back using
        prepare_ifc_view metadata rows. expressId is only local to this exact file.
        """
        model, products = _model(ifc_text)
        objects = []
        for item in products:
            objects.append(
                {
                    "globalId": item.GlobalId,
                    "expressId": item.id(),
                    "ifcType": item.is_a(),
                    "name": item.Name,
                    "properties": ifcopenshell.util.element.get_psets(item),
                }
            )
        return _bounded(
            {
                "kind": "ifc.objects",
                "schemaVersion": "1",
                "modelSha256": hashlib.sha256(ifc_text.encode()).hexdigest(),
                "ifcSchema": model.schema,
                "objects": objects,
            }
        )

    @mcp.tool(
        annotations={"readOnlyHint": True, "idempotentHint": True},
        app=AppConfig(resource_uri=APP_URI),
        output_schema=IfcView.model_json_schema(),
    )
    def prepare_ifc_view(
        ifc_text: str,
        metadata: list[ObjectMetadata] | None = None,
        colour_by: str | None = None,
    ) -> ToolResult:
        """Read get_ifc_guide first. Create a portable IFC view with metadata overlays keyed by IFC GlobalId.

        Bind calculation/Map outputs as [{globalId, values: {status, utilisation, ...}}].
        Each object may occur once; unknown IDs are rejected. Values are finite JSON
        scalars. colour_by names an overlay key. IFC source is preserved verbatim.
        A successful result can be saved by the host and reopened without rerunning.
        """
        _, products = _model(ifc_text)
        ids = {item.GlobalId for item in products}
        seen = set()
        rows = []
        for row in metadata or []:
            if row.globalId not in ids or row.globalId in seen:
                raise ToolError(f"Unknown or duplicate GlobalId: {row.globalId}")
            seen.add(row.globalId)
            if len(row.values) > 128 or any(not key or len(key) > 128 for key in row.values):
                raise ToolError(
                    "Metadata permits up to 128 nonempty keys of at most 128 characters."
                )
            if any(isinstance(v, float) and not math.isfinite(v) for v in row.values.values()):
                raise ToolError("Metadata numbers must be finite.")
            rows.append(row.model_dump())
        if colour_by is not None and colour_by not in {k for row in rows for k in row["values"]}:
            raise ToolError("colour_by must name an assigned metadata key.")
        return _bounded(
            {
                "kind": "ifc.view",
                "schemaVersion": "1",
                "ifcText": ifc_text,
                "modelSha256": hashlib.sha256(ifc_text.encode()).hexdigest(),
                "metadata": rows,
                "colourBy": colour_by,
            }
        )

    @mcp.resource(
        uri=APP_URI,
        name="IFC viewer",
        mime_type="text/html;profile=mcp-app",
        meta={"ui": app_config_to_meta_dict(AppConfig())},
    )
    def viewer() -> str:
        return _APP.read_text(encoding="utf-8")

    return mcp


def main() -> None:
    create_ifc_viewer_server().run(transport="http", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
