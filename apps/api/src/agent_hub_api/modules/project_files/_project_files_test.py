import pytest

from agent_hub_api.modules.project_files import (
    ProjectFileNotFound,
    create_memory_project_files,
)


@pytest.mark.asyncio
async def test_project_files_are_shared_within_only_one_project() -> None:
    files = create_memory_project_files()
    first_thread = files.deep_agent_backend("project-a")
    second_thread = files.deep_agent_backend("project-a")
    other_project = files.deep_agent_backend("project-b")

    written = await first_thread.awrite("/project/notes/check.md", "# Check\nOne")
    shared = await second_thread.aread("/project/notes/check.md")
    isolated = await other_project.aread("/project/notes/check.md")

    assert written.error is None
    assert written.path == "/project/notes/check.md"
    assert shared.file_data == {"content": "# Check\nOne", "encoding": "utf-8"}
    assert isolated.error == "Error: File '/notes/check.md' not found"


@pytest.mark.asyncio
async def test_backend_rejects_host_paths_escape_and_reserved_artifact_writes() -> None:
    backend = create_memory_project_files().deep_agent_backend("project-a")

    host_path = await backend.awrite("/tmp/server.txt", "no")
    escaped = await backend.awrite("/project/../server.txt", "no")
    artifact = await backend.awrite("/project/.artifacts/calculation.json", "no")

    assert host_path.error == "Error: files must be stored under /project or /scratch"
    assert escaped.error == "Error: Path traversal with '..' is not allowed"
    assert artifact.error is not None and "Artifact Module" in artifact.error


@pytest.mark.asyncio
async def test_exact_edit_reports_stale_or_ambiguous_content() -> None:
    backend = create_memory_project_files().deep_agent_backend("project-a")
    await backend.awrite("/project/check.md", "same\nsame\n")

    ambiguous = await backend.aedit("/project/check.md", "same", "changed")
    changed = await backend.aedit("/project/check.md", "same", "changed", replace_all=True)
    stale = await backend.aedit("/project/check.md", "same", "again")

    assert ambiguous.error is not None and "appears 2 times" in ambiguous.error
    assert changed.occurrences == 2
    assert stale.error is not None and "was not found" in stale.error


@pytest.mark.asyncio
async def test_limits_search_and_safe_preview_use_the_same_module() -> None:
    files = create_memory_project_files(max_bytes=12)
    await files.write("project-a", "/small.md", "beam check")

    preview = await files.load("project-a", "/small.md")
    search = await files.search("project-a", "beam")
    listing = await files.deep_agent_backend("project-a").als("/project")

    assert preview.content == "beam check"
    assert search.matches == [{"path": "/small.md", "line": 1, "text": "beam check"}]
    assert listing.entries == [
        {
            "path": "/project/small.md",
            "is_dir": False,
            "size": 10,
            "modified_at": preview.updated_at.isoformat(),
        }
    ]
    with pytest.raises(ProjectFileNotFound):
        await files.load("project-b", "/small.md")

    oversized = await files.deep_agent_backend("project-a").awrite("/project/large.md", "x" * 13)
    assert oversized.error is not None and "configured 12-byte limit" in oversized.error
