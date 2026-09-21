from datetime import UTC, datetime

import pytest

from agent_hub_api.modules.project_files import (
    ProjectFile,
    ProjectFileLimitExceeded,
    ProjectFileNotFound,
    ProjectFileSearchMatch,
    ProjectFilesModule,
    create_memory_project_files,
)
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module


class ArtifactBackedFileStore:
    async def list(self, project_id: str) -> tuple[ProjectFile, ...]:
        timestamp = datetime.now(UTC)
        return (
            ProjectFile(project_id, "/.artifacts/check.json", "{}", 1, timestamp, timestamp),
            ProjectFile(project_id, "/notes/check.md", "# Check", 1, timestamp, timestamp),
        )


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


@pytest.mark.asyncio
async def test_visible_project_files_exclude_artifact_backing_documents() -> None:
    projects = create_memory_project_module()
    project = await projects.create(ProjectAccess(subject="alice"), "Bridge")
    files = ProjectFilesModule(
        ArtifactBackedFileStore(),
        projects,
        max_bytes=1_000_000,
        max_files=1_000,
        search_max_matches=100,
    )

    visible = await files.list_visible(ProjectAccess(subject="alice"), project.id)

    assert [file.path for file in visible] == ["/notes/check.md"]
