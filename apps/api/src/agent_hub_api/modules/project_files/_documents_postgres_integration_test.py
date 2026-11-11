"""Binary sources and generated text survive reconstruction of the production adapters."""

import os
from pathlib import Path

import pytest
from pydantic import PostgresDsn

from agent_hub_api.modules.project_files import (
    ProjectFileAccess,
    ProjectFileLimitExceeded,
    create_postgres_project_files,
)
from agent_hub_api.modules.projects import ProjectAccess, create_postgres_project_module
from agent_hub_api.settings import Settings


@pytest.mark.asyncio
async def test_original_and_searchable_pages_are_persisted_atomically() -> None:
    url = os.environ.get("AGENT_HUB_ISOLATED_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires an explicitly isolated migrated PostgreSQL database")
    settings = Settings(database_url=PostgresDsn(url))
    projects = create_postgres_project_module(settings)
    project = await projects.create(ProjectAccess("document-test"), "Document persistence")
    owner = ProjectFileAccess("document-test")
    source = (Path(__file__).parents[6] / "tests/fixtures/documents/bridge.pdf").read_bytes()
    files = create_postgres_project_files(settings, projects)
    assert files.documents is not None
    document = await files.documents.upload(owner, project.id, "bridge.pdf", source)
    restored = create_postgres_project_files(settings, create_postgres_project_module(settings))
    assert restored.documents is not None
    record = await restored.documents.load(owner, project.id, document["id"])
    assert record.source == source
    assert record.summary == document
    assert any(
        "12.5" in match.text for match in (await restored.search(project.id, "12.5")).matches
    )
    limited = create_postgres_project_files(
        Settings(database_url=PostgresDsn(url), project_file_max_files=1), projects
    )
    assert limited.documents is not None
    with pytest.raises(ProjectFileLimitExceeded):
        await limited.documents.upload(owner, project.id, "overflow.pdf", source)
    assert len(await restored.documents.list(owner, project.id)) == 1
    await restored.documents.delete(owner, project.id, document["id"])
    assert not await restored.documents.list(owner, project.id)
    assert not await restored.list(project.id)
