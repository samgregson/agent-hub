import pytest

from agent_hub_api.modules.project_files import (
    create_memory_project_files,
)
from agent_hub_api.modules.projects import create_memory_project_module

from ._project_files_backend import create_project_files_backend


@pytest.mark.asyncio
async def test_project_files_are_shared_within_only_one_project() -> None:
    files = create_memory_project_files(create_memory_project_module())
    first_thread = create_project_files_backend(files, "project-a")
    second_thread = create_project_files_backend(files, "project-a")
    other_project = create_project_files_backend(files, "project-b")

    written = await first_thread.awrite("/project/notes/check.md", "# Check\nOne")
    shared = await second_thread.aread("/project/notes/check.md")
    isolated = await other_project.aread("/project/notes/check.md")

    assert written.error is None
    assert written.path == "/project/notes/check.md"
    assert shared.file_data == {"content": "# Check\nOne", "encoding": "utf-8"}
    assert isolated.error == "Error: File '/notes/check.md' not found"


@pytest.mark.asyncio
async def test_backend_rejects_host_paths_escape_and_reserved_artifact_writes() -> None:
    backend = create_project_files_backend(
        create_memory_project_files(create_memory_project_module()), "project-a"
    )

    host_path = await backend.awrite("/tmp/server.txt", "no")
    escaped = await backend.awrite("/project/../server.txt", "no")
    artifact = await backend.awrite("/project/.artifacts/calculation.json", "no")

    assert host_path.error == "Error: files must be stored under /project or /scratch"
    assert escaped.error == "Error: Path traversal with '..' is not allowed"
    assert artifact.error is not None and "Artifact Module" in artifact.error


@pytest.mark.asyncio
async def test_exact_edit_reports_stale_or_ambiguous_content() -> None:
    backend = create_project_files_backend(
        create_memory_project_files(create_memory_project_module()), "project-a"
    )
    await backend.awrite("/project/check.md", "same\nsame\n")

    ambiguous = await backend.aedit("/project/check.md", "same", "changed")
    changed = await backend.aedit("/project/check.md", "same", "changed", replace_all=True)
    stale = await backend.aedit("/project/check.md", "same", "again")

    assert ambiguous.error is not None and "appears 2 times" in ambiguous.error
    assert changed.occurrences == 2
    assert stale.error is not None and "was not found" in stale.error
