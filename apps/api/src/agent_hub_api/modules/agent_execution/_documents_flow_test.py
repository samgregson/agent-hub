"""Real agent filesystem and multimodal tools over a real converted document.

The model is deterministic: this tests orchestration, not live-model reasoning.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from agent_hub_api.modules.project_files import ProjectFileAccess, create_memory_project_files
from agent_hub_api.modules.projects import ProjectAccess, create_memory_project_module
from agent_hub_api.settings import Settings

from ._deep_agent import PostgresDeepAgentRunner


class DocumentModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "document-search-test"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "DocumentModel":
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        args: dict[str, Any]
        results = [m for m in messages if isinstance(m, ToolMessage)]
        if not results:
            name, args = "list_project_documents", {}
        else:
            document = json.loads(str(results[0].content))["documents"][0]
            if len(results) == 1:
                name, args = (
                    "grep",
                    {"pattern": "12.5", "path": "/project/.documents", "glob": "*.md"},
                )
            elif len(results) == 2:
                assert "001.md" in str(results[-1].content)
                name, args = "read_file", {"file_path": document["textPath"]}
            elif len(results) == 3:
                assert "12.5 metres" in str(results[-1].content)
                name, args = (
                    "view_project_document_page",
                    {"document_id": document["id"], "page": 1},
                )
            else:
                assert any(
                    block.get("type") in {"image", "image_url"}
                    for block in results[-1].content
                    if isinstance(block, dict)
                )
                return ChatResult(
                    generations=[
                        ChatGeneration(
                            message=AIMessage(
                                content="Bridge span: 12.5 metres (bridge.pdf, page 1)."
                            )
                        )
                    ]
                )
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[{"id": f"document-{len(results)}", "name": name, "args": args}],
                    )
                )
            ]
        )


@pytest.mark.asyncio
async def test_main_agent_can_discover_grep_read_and_visually_inspect_uploaded_pdf() -> None:
    projects = create_memory_project_module()
    project = await projects.create(ProjectAccess("alice"), "Document reasoning")
    files = create_memory_project_files(projects)
    assert files.documents is not None
    source = (Path(__file__).parents[6] / "tests/fixtures/documents/bridge.pdf").read_bytes()
    await files.documents.upload(ProjectFileAccess("alice"), project.id, "bridge.pdf", source)
    before = await files.list(project.id)
    runner = PostgresDeepAgentRunner(Settings(environment="test"), files)
    runner._model = DocumentModel()
    runner._checkpointer = InMemorySaver()
    agent = await runner._agent_for(
        project.id, thread_id="document-thread", run_id="document-run", subject="alice"
    )
    result = await agent.graph.ainvoke(
        {
            "messages": [
                HumanMessage(
                    content="Find the bridge span in the uploaded PDF and inspect its drawing."
                )
            ]
        },
        config={"configurable": {"thread_id": "document-thread"}, "recursion_limit": 25},
    )
    assert not result.get("__interrupt__")
    assert result["messages"][-1].content == "Bridge span: 12.5 metres (bridge.pdf, page 1)."
    assert await files.list(project.id) == before
