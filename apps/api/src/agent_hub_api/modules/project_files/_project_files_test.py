import pytest

from agent_hub_api.modules.project_files import (
    ProjectFileLimitExceeded,
    ProjectFileNotFound,
    ProjectFileSearchMatch,
    create_memory_project_files,
)
from agent_hub_api.modules.projects import create_memory_project_module


@pytest.mark.asyncio
async def test_limits_search_and_load_use_the_same_module() -> None:
    files = create_memory_project_files(create_memory_project_module(), max_bytes=12)
    await files.write("project-a", "/small.md", "beam check")

    preview = await files.load("project-a", "/small.md")
    search = await files.search("project-a", "beam")

    assert preview.content == "beam check"
    assert search.matches == (ProjectFileSearchMatch("/small.md", 1, "beam check"),)
    with pytest.raises(ProjectFileNotFound):
        await files.load("project-b", "/small.md")

    with pytest.raises(ProjectFileLimitExceeded, match="configured 12-byte limit"):
        await files.write("project-a", "/large.md", "x" * 13)
