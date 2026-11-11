"""Check discoverable MCP tool metadata for a first-party Plugin server factory."""

import asyncio
import importlib
import re
import sys
from pathlib import Path

from fastmcp.client import Client
from jsonschema.validators import validator_for


async def check(factory_path: str) -> None:
    module_name, factory_name = factory_path.split(":", 1)
    server = getattr(importlib.import_module(module_name), factory_name)()
    async with Client(server) as client:
        tools = await client.list_tools()
        if not tools:
            raise AssertionError("Plugin exposes no tools")
        names = set()
        for tool in tools:
            if not tool.name or tool.name in names:
                raise AssertionError(f"Invalid or duplicate tool name: {tool.name!r}")
            names.add(tool.name)
            if not tool.description or not tool.description.strip():
                raise AssertionError(f"{tool.name}: missing tool description")
            for label, schema in (("input", tool.input_schema), ("output", tool.output_schema)):
                if schema is None:
                    if label == "input":
                        raise AssertionError(f"{tool.name}: missing input schema")
                    continue
                validator_for(schema).check_schema(schema)
                if schema.get("type") != "object":
                    raise AssertionError(f"{tool.name}: {label} schema must describe an object")
        print(f"{factory_path}: validated {len(tools)} tool contracts")


def check_matrix_coverage() -> None:
    root = Path(__file__).resolve().parents[1]
    projects = {
        path.name for path in (root / "plugins").iterdir() if (path / "pyproject.toml").is_file()
    }
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    matrix = workflow.split("\n  plugin-contracts:", 1)[1]
    configured = set(re.findall(r"^\s+- project: ([\w-]+)\s*$", matrix, re.MULTILINE))
    missing = projects - configured
    if missing:
        raise AssertionError(f"Plugins missing from the contract CI matrix: {sorted(missing)}")


if __name__ == "__main__":
    check_matrix_coverage()
    asyncio.run(check(sys.argv[1]))
