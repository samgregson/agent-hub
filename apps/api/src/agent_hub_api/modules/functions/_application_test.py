import pytest

from agent_hub_api.modules.functions import (
    FunctionModule,
    FunctionNotFound,
    FunctionRuntimeIdentity,
    FunctionValidationError,
    MemoryFunctionStore,
)
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {"load": {"type": "number"}},
    "required": ["load"],
    "additionalProperties": False,
}
_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "number"}},
    "required": ["value"],
    "additionalProperties": False,
}


class _Runner:
    async def identity(self) -> FunctionRuntimeIdentity:
        return FunctionRuntimeIdentity("deno:test;pyodide:test", "a" * 64)

    async def execute(
        self, source: str, inputs: dict[str, object], parameters: dict[str, object]
    ) -> tuple[object, str]:
        assert source.startswith("def transform(inputs, parameters):")
        assert inputs == {"load": 3}
        assert parameters == {"factor": 2}
        load = inputs["load"]
        factor = parameters["factor"]
        assert isinstance(load, int) and isinstance(factor, int)
        return {"value": load * factor}, "deno:test;pyodide:test"


@pytest.mark.asyncio
async def test_function_preview_uses_named_inputs_without_saving_a_run() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Functions")
    functions = FunctionModule(projects, MemoryFunctionStore(), _Runner())
    function = await functions.define(
        owner,
        project.id,
        "Double load",
        "def transform(inputs, parameters):\n    return {}\n",
        _INPUT_SCHEMA,
        _OUTPUT_SCHEMA,
    )

    preview = await functions.preview(owner, project.id, function.id, {"load": 3}, {"factor": 2})

    assert preview.output == {"value": 6}
    assert preview.runtime == "deno:test;pyodide:test"
    assert preview.source_hash == function.source_hash


@pytest.mark.asyncio
async def test_function_preview_rejects_inputs_and_outputs_outside_contracts() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    project = await projects.create(owner, "Functions")
    functions = FunctionModule(projects, MemoryFunctionStore(), _Runner())
    function = await functions.define(
        owner,
        project.id,
        "Double load",
        "def transform(inputs, parameters):\n    return {}\n",
        _INPUT_SCHEMA,
        _OUTPUT_SCHEMA,
    )

    with pytest.raises(FunctionValidationError, match="input"):
        await functions.preview(owner, project.id, function.id, {"other": 3}, {})

    class InvalidOutputRunner(_Runner):
        async def execute(
            self, source: str, inputs: dict[str, object], parameters: dict[str, object]
        ) -> tuple[object, str]:
            return {"value": "six"}, "deno:test;pyodide:test"

    functions = FunctionModule(projects, MemoryFunctionStore(), InvalidOutputRunner())
    function = await functions.define(
        owner,
        project.id,
        "Double load",
        "def transform(inputs, parameters):\n    return {}\n",
        _INPUT_SCHEMA,
        _OUTPUT_SCHEMA,
    )
    with pytest.raises(FunctionValidationError, match="output schema"):
        await functions.preview(owner, project.id, function.id, {"load": 3}, {})


@pytest.mark.asyncio
async def test_function_definition_is_project_scoped_and_revisions_keep_identity() -> None:
    projects = create_memory_project_module()
    owner = ProjectAccess(subject="sam")
    other = ProjectAccess(subject="alex")
    project = await projects.create(owner, "Functions")
    functions = FunctionModule(projects, MemoryFunctionStore())
    function = await functions.define(
        owner,
        project.id,
        "Double load",
        "def transform(inputs, parameters):\n    return {}\n",
        _INPUT_SCHEMA,
        _OUTPUT_SCHEMA,
    )
    revised = await functions.revise(
        owner,
        project.id,
        function.id,
        "Triple load",
        "def transform(inputs, parameters):\n    return {}\n",
        _INPUT_SCHEMA,
        _OUTPUT_SCHEMA,
    )

    assert revised.id == function.id
    assert revised.revision == 2
    assert [item.id for item in await functions.list(owner, project.id)] == [function.id]
    with pytest.raises(FunctionNotFound):
        await functions.load(other, project.id, function.id)

    await functions.delete(owner, project.id, function.id)
    with pytest.raises(FunctionNotFound):
        await functions.load(owner, project.id, function.id)


@pytest.mark.asyncio
async def test_function_definition_rejects_invalid_source_or_schema() -> None:
    projects = create_memory_project_module()
    access = ProjectAccess(subject="sam")
    project = await projects.create(access, "Functions")
    functions = FunctionModule(projects, MemoryFunctionStore())

    with pytest.raises(FunctionValidationError, match="source"):
        await functions.define(access, project.id, "Bad", " ", _INPUT_SCHEMA, _OUTPUT_SCHEMA)
    with pytest.raises(FunctionValidationError, match="Python"):
        await functions.define(
            access, project.id, "Bad", "not Python!", _INPUT_SCHEMA, _OUTPUT_SCHEMA
        )
    with pytest.raises(FunctionValidationError, match="input schema"):
        await functions.define(access, project.id, "Bad", "pass", {"type": "array"}, _OUTPUT_SCHEMA)
    with pytest.raises(FunctionValidationError, match="output schema"):
        await functions.define(access, project.id, "Bad", "pass", _INPUT_SCHEMA, {"type": "wat"})
