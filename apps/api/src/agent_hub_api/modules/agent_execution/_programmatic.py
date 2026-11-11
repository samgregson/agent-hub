"""Native PTC with an explicit read-only capability set and no persistent interpreter state."""

import hashlib
import json
from collections.abc import Sequence
from typing import Annotated, Any, cast

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, StructuredTool, tool
from langchain_quickjs import CodeInterpreterMiddleware
from pydantic import Field

from agent_hub_api.modules.project_files import ProjectFileAccess, ProjectFilesModule

# No writes, previews that execute code, Workflow preparation/execution, or subagents.
_READ_TOOL_NAMES = frozenset(
    {
        "list_project_files",
        "discover_project_plugins",
        "discover_project_artifacts",
        "load_project_artifact",
        "discover_project_datasets",
        "load_project_dataset",
        "discover_project_functions",
        "load_project_function",
        "list_project_workflows",
        "load_project_workflow",
        "discover_project_file_sources",
        "load_project_workflow_run",
    }
)


class _ReadOnlyInterpreter(CodeInterpreterMiddleware[Any, Any]):
    def _build_tool(self) -> BaseTool:
        eval_tool = cast(StructuredTool, super()._build_tool())
        original = eval_tool.coroutine
        assert original is not None

        async def invoke(runtime: ToolRuntime[None, Any], code: str) -> Any:
            result = await original(runtime, code)
            if (
                isinstance(result.content, str)
                and '<error type="TypeError">not a function' in result.content
            ):
                result.content += (
                    "\nA called function may be unavailable in eval. Check the exposed tool names; "
                    "eval only exposes reviewed read-only tools. Call other Plugin tools normally "
                    "outside eval, and do not retry unchanged code."
                )
            return result

        eval_tool.coroutine = invoke
        return eval_tool


def project_read_tools(
    files: ProjectFilesModule,
    project_id: str,
    subject: str,
) -> tuple[BaseTool, BaseTool]:
    access = ProjectFileAccess(subject=subject)

    @tool
    async def list_project_files(query: str = "", offset: int = 0, limit: int = 50) -> str:
        """List authorized Project File paths, versions and sizes; limit is 1–100, offset >= 0."""
        if offset < 0 or not 1 <= limit <= 100:
            return json.dumps(
                {
                    "error": {"code": "invalid_pagination", "message": "Invalid offset or limit."},
                    "nextStep": "Retry with offset >= 0 and limit between 1 and 100.",
                }
            )
        items = sorted(
            (
                item
                for item in await files.list_visible(access, project_id)
                if query.casefold() in item.path.casefold()
            ),
            key=lambda item: item.path,
        )
        return json.dumps(
            {
                "files": [
                    {
                        "path": f"/project{item.path}",
                        "version": item.version,
                        "sizeBytes": len(item.content.encode("utf-8")),
                    }
                    for item in items[offset : offset + limit]
                ],
                "nextOffset": offset + limit if offset + limit < len(items) else None,
            }
        )

    @tool
    async def read_project_file(
        path: str, expected_version: Annotated[int, Field(strict=True, ge=1)]
    ) -> dict[str, object]:
        """Read exact Project text into the interpreter. Returns path, version, sha256 and content.

        Discover a real path/version with list_project_files. Use only within eval so the
        file stays in interpreter variables, not model messages. No local paths or URLs.
        """
        if not path.startswith("/project/"):
            raise ValueError("Only /project/ files are available.")
        file = await files.preview(access, project_id, path.removeprefix("/project"))
        if file.version != expected_version:
            raise ValueError("Project File changed; discover its current version and review it.")
        return {
            "path": f"/project{file.path}",
            "version": file.version,
            "sha256": hashlib.sha256(file.content.encode("utf-8")).hexdigest(),
            "content": file.content,
        }

    return list_project_files, read_project_file


def read_only_interpreter(
    agent_tools: Sequence[BaseTool],
    mcp_tools: Sequence[BaseTool],
    file_tools: Sequence[BaseTool],
) -> CodeInterpreterMiddleware[Any, Any]:
    # Explicit objects take precedence over ordinary tools of the same name. In
    # particular, never bridge normal MCP wrappers that automatically save snapshots.
    allowed: list[str | BaseTool] = [
        *file_tools,
        *mcp_tools,
        *(tool for tool in agent_tools if tool.name in _READ_TOOL_NAMES),
    ]
    return _ReadOnlyInterpreter(
        ptc=allowed,
        subagents=False,
        mode="call",
        capture_console=False,
        memory_limit=64 * 1024 * 1024,
        timeout=20,
        max_ptc_calls=32,
        max_result_chars=8_000,
    )
