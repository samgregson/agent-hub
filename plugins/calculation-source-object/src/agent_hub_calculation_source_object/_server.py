from __future__ import annotations

import asyncio
import json
import math
import re
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.apps import AppConfig, app_config_to_meta_dict
from fastmcp.exceptions import ToolError

RUN_CALCULATION_TOOL_NAME = "run_calculation"
REPORT_APP_RESOURCE_URI = "ui://agent-hub-calculation-source-object/report.html"
_APP_HTML_PATH = Path(__file__).parents[2] / "app" / "index.html"
_APP_BUNDLE_PATH = Path(__file__).parents[2] / "app" / "dist" / "report.js"
_SOURCE_BYTE_LIMIT = 64_000
_INPUT_BYTE_LIMIT = 32_000
_OUTPUT_BYTE_LIMIT = 768_000
_EXECUTION_TIMEOUT_SECONDS = 12
_RUNNER_PATH = Path("/app/worker.mjs")
_DENO_PATH = "/usr/bin/deno"
_FUNCTION_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_execution_lock = asyncio.Semaphore(1)


async def _read_bounded(stream: asyncio.StreamReader, maximum: int) -> bytes:
    output = bytearray()
    while chunk := await stream.read(8192):
        output.extend(chunk)
        if len(output) > maximum:
            raise ValueError("output_limit")
    return bytes(output)


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        process.kill()
    except ProcessLookupError:
        return
    await process.wait()


async def _execute_source(
    source: str, function: str, inputs: dict[str, int | float]
) -> dict[str, Any]:
    source_bytes = source.encode("utf-8")
    if not source.strip() or len(source_bytes) > _SOURCE_BYTE_LIMIT:
        raise ToolError(
            f"Calculation source must be between 1 and {_SOURCE_BYTE_LIMIT} UTF-8 bytes."
        )
    if not _FUNCTION_NAME.fullmatch(function):
        raise ToolError("The calculation function must be a Python identifier.")
    try:
        finite_inputs = all(
            type(value) in (int, float) and math.isfinite(value) for value in inputs.values()
        )
    except OverflowError:
        finite_inputs = False
    if not finite_inputs:
        raise ToolError("Calculation inputs must be finite numbers.")

    input_json = json.dumps(inputs, allow_nan=False, separators=(",", ":"))
    if len(input_json.encode("utf-8")) > _INPUT_BYTE_LIMIT:
        raise ToolError(f"Calculation inputs exceed {_INPUT_BYTE_LIMIT} UTF-8 bytes.")

    payload = json.dumps(
        {"source": source, "function": function, "inputs": inputs},
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > _SOURCE_BYTE_LIMIT + _INPUT_BYTE_LIMIT + 256:
        raise ToolError("The calculation request exceeded its size limit.")

    process: asyncio.subprocess.Process | None = None
    try:
        async with asyncio.timeout(_EXECUTION_TIMEOUT_SECONDS):
            async with _execution_lock:
                process = await asyncio.create_subprocess_exec(
                    _DENO_PATH,
                    "run",
                    "--cached-only",
                    "--no-prompt",
                    "--allow-read=/app,/deno-dir",
                    "--deny-net",
                    "--deny-env",
                    "--deny-run",
                    "--deny-ffi",
                    str(_RUNNER_PATH),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env={"DENO_DIR": "/deno-dir", "DENO_NO_PROMPT": "1"},
                )
                assert process.stdin is not None and process.stdout is not None
                process.stdin.write(payload)
                await process.stdin.drain()
                process.stdin.close()
                reader = asyncio.create_task(_read_bounded(process.stdout, _OUTPUT_BYTE_LIMIT))
                output = await reader
                await process.wait()
                if process.returncode != 0:
                    raise ToolError("The calculation runner exited unsuccessfully.")
    except TimeoutError as error:
        if process is not None:
            await _stop_process(process)
        raise ToolError(
            "The calculation exceeded its 12-second limit, including queue wait time."
        ) from error
    except ValueError as error:
        if process is not None:
            await _stop_process(process)
        raise ToolError("The calculation output exceeded its size limit.") from error
    except BaseException:
        if process is not None:
            await _stop_process(process)
        raise

    try:
        response = json.loads(output)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ToolError("The calculation runner returned an invalid response.") from error
    if not isinstance(response, dict) or response.get("ok") is not True:
        diagnostics = response.get("diagnostics") if isinstance(response, dict) else None
        nested = response.get("response") if isinstance(response, dict) else None
        if diagnostics is None and isinstance(nested, dict):
            diagnostics = nested.get("diagnostics")
        summary = "; ".join(
            str(item.get("message", "Calculation failed"))
            for item in diagnostics or []
            if isinstance(item, dict)
        )
        raise ToolError(summary[:2_000] or "Calculation execution failed.")
    execution = response.get("execution")
    if not isinstance(execution, dict):
        raise ToolError("The calculation runner returned no execution record.")
    if execution.get("assets"):
        raise ToolError("This version accepts a single source file without local figure assets.")
    return execution


def create_calculation_source_object_server() -> FastMCP:
    """Create a portable MCP server for running and viewing CSO calculations."""
    mcp = FastMCP("agent-hub-calculation-source-object")

    @mcp.tool(
        name=RUN_CALCULATION_TOOL_NAME,
        annotations={"idempotentHint": True},
        app=AppConfig(resource_uri=REPORT_APP_RESOURCE_URI),
    )
    async def run_calculation(
        source: str,
        function: str,
        inputs: dict[str, int | float],
    ) -> dict[str, object]:
        """Execute one CalculationSourceObject Python source and return its captured report data.

        Provide a single .cso.py source file, the decorated calculation function name, and
        finite numeric inputs. Agent Hub Workflows can bind Project File contents to source;
        ordinary agent tool calls can provide source text directly. Execution captures the
        exact source and inputs. This reports captured execution; it does not run independent
        formula or reference checks, and it does not establish engineering approval.
        """
        execution = await _execute_source(source, function, inputs)
        return {
            "kind": "calculation-source-object.execution",
            "schemaVersion": "1",
            "sourceSha256": execution.get("entry", {}).get("sourceHash"),
            "function": function,
            "inputs": inputs,
            "execution": execution,
            "checks": {
                "formulaConsistency": "not_run",
                "independentReferenceAgreement": "not_run",
                "visualInspection": "not_run",
            },
        }

    @mcp.resource(
        uri=REPORT_APP_RESOURCE_URI,
        name="Calculation report",
        description="Read-only report viewer for a saved CalculationSourceObject execution.",
        mime_type="text/html;profile=mcp-app",
        annotations={"readOnlyHint": True, "idempotentHint": True},
        meta={"ui": app_config_to_meta_dict(AppConfig())},
    )
    async def report_view() -> str:
        html = _APP_HTML_PATH.read_text(encoding="utf-8")
        bundle = _APP_BUNDLE_PATH.read_text(encoding="utf-8")
        return html.replace("<!-- REPORT_BUNDLE -->", f"<script>{bundle}</script>")

    return mcp


def main() -> None:
    create_calculation_source_object_server().run(transport="http", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
