import logging
from collections.abc import AsyncIterator
from typing import Annotated

from ag_ui.core import RunAgentInput, RunErrorEvent
from ag_ui.encoder import EventEncoder
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent_hub_api.contracts import AgentRun as AgentRunResponse
from agent_hub_api.modules.agent_execution import AgentRun
from agent_hub_api.modules.agent_transport._application import (
    AgentThreadAccess,
    AgentThreadNotFound,
    AgentTransportModule,
    DuplicateAgentTransportRun,
)
from agent_hub_api.modules.identity import (
    IdentityEvidence,
    IdentityModule,
    IdentityUnavailable,
    RequestContext,
)

logger = logging.getLogger(__name__)


class ThreadHistoryResponse(BaseModel):
    messages: list[dict[str, object]]


def _run_response(run: AgentRun) -> AgentRunResponse:
    return AgentRunResponse.model_validate(
        {
            "id": run.id,
            "threadId": run.thread_id,
            "status": run.status.value,
            "createdAt": run.created_at,
            "updatedAt": run.updated_at,
            "error": run.error,
        }
    )


def create_agent_transport_router(
    identity: IdentityModule,
    agent_transport: AgentTransportModule,
) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/threads/{thread_id}", tags=["agent"])

    async def request_context(request: Request) -> RequestContext:
        try:
            return identity.resolve(IdentityEvidence(headers=request.headers))
        except IdentityUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated platform identity is required",
            ) from error

    Context = Annotated[RequestContext, Depends(request_context)]

    def access(project_id: str, thread_id: str, context: RequestContext) -> AgentThreadAccess:
        return AgentThreadAccess(
            subject=context.subject,
            request_id=context.request_id,
            project_id=project_id,
            thread_id=thread_id,
        )

    @router.get("/runs", response_model=list[AgentRunResponse])
    async def list_runs(
        project_id: str, thread_id: str, context: Context
    ) -> list[AgentRunResponse]:
        try:
            runs = await agent_transport.list_runs(access(project_id, thread_id, context))
        except AgentThreadNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found"
            ) from error
        return [_run_response(run) for run in runs]

    @router.get("/history", response_model=ThreadHistoryResponse)
    async def load_history(
        project_id: str, thread_id: str, context: Context
    ) -> ThreadHistoryResponse:
        try:
            messages = await agent_transport.load_messages(access(project_id, thread_id, context))
        except AgentThreadNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found"
            ) from error
        return ThreadHistoryResponse(
            messages=[
                message.model_dump(mode="json", by_alias=True, exclude_none=True)
                for message in messages
            ]
        )

    @router.post("/agent")
    async def stream_agent(
        project_id: str,
        thread_id: str,
        input_data: RunAgentInput,
        request: Request,
        context: Context,
    ) -> StreamingResponse:
        if input_data.thread_id != thread_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="AG-UI threadId does not match the authorized Thread",
            )
        if not input_data.run_id or len(input_data.run_id) > 128:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="AG-UI runId must contain between 1 and 128 characters",
            )

        try:
            events = await agent_transport.start(access(project_id, thread_id, context), input_data)
        except AgentThreadNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found"
            ) from error
        except DuplicateAgentTransportRun as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Agent Run already exists",
            ) from error

        encoder = EventEncoder(accept=request.headers.get("accept") or "")

        async def encoded_events() -> AsyncIterator[str]:
            try:
                async for event in events:
                    yield encoder.encode(event)
            except Exception:
                logger.exception(
                    "Agent Run stream failed",
                    extra={"run_id": input_data.run_id, "thread_id": thread_id},
                )
                yield encoder.encode(
                    RunErrorEvent(
                        message="The agent run failed. Retry or inspect its status.",
                        code="AGENT_RUN_FAILED",
                    )
                )

        return StreamingResponse(
            encoded_events(),
            media_type=encoder.get_content_type(),
            headers={"Cache-Control": "no-cache, no-transform"},
        )

    return router
