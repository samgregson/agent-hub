import io
import json
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse, StreamingResponse
from starlette.routing import Route

from agent_hub_api.main import create_app
from agent_hub_api.modules.observability._http import RequestLoggingMiddleware, logger
from agent_hub_api.modules.observability._trace import trace_logger, trace_plugin_operation
from agent_hub_api.settings import Settings


@pytest.mark.asyncio
async def test_access_log_correlates_response_without_logging_request_data() -> None:
    async def ready(_: Settings) -> None:
        return None

    app = create_app(settings=Settings(environment="test"), readiness_check=ready)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/health/ready?secret=do-not-log", headers={"Authorization": "Bearer private"}
            )
    finally:
        logger.removeHandler(handler)

    request_id = response.headers["X-Request-Id"]
    assert str(UUID(request_id)) == request_id
    entries = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert len(entries) == 1
    assert entries[0] == {
        "event": "http_request",
        "request_id": request_id,
        "method": "GET",
        "route": "/health/ready",
        "status": 200,
        "duration_ms": entries[0]["duration_ms"],
    }
    assert "do-not-log" not in str(entries)
    assert "private" not in str(entries)


@pytest.mark.asyncio
async def test_correlation_header_does_not_buffer_streamed_response() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"first\n"
        yield b"second\n"

    async def stream(_: object) -> StreamingResponse:
        return StreamingResponse(chunks(), media_type="text/plain")

    app = RequestLoggingMiddleware(Starlette(routes=[Route("/stream", stream)]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/stream")

    assert response.status_code == 200
    assert response.text == "first\nsecond\n"
    assert str(UUID(response.headers["X-Request-Id"])) == response.headers["X-Request-Id"]


@pytest.mark.asyncio
async def test_rejected_oversized_request_keeps_a_correlation_id() -> None:
    app = create_app(settings=Settings(environment="test", request_body_max_bytes=1_024))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/projects", content=b"x" * 1_025)

    assert response.status_code == 413
    assert str(UUID(response.headers["X-Request-Id"])) == response.headers["X-Request-Id"]


@pytest.mark.asyncio
async def test_remote_span_correlates_without_tool_arguments_or_secret_headers() -> None:
    async def invoke(_: object) -> PlainTextResponse:
        async with trace_plugin_operation("mcp.tool", "foundation-fixture"):
            return PlainTextResponse("ok")

    app = RequestLoggingMiddleware(Starlette(routes=[Route("/invoke", invoke, methods=["POST"])]))
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    trace_logger.addHandler(handler)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/invoke?secret=not-in-trace",
                content=b"sensitive-tool-arguments",
                headers={"Authorization": "Bearer private"},
            )
    finally:
        trace_logger.removeHandler(handler)

    spans = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(spans) == 2
    remote, root = spans
    assert remote["trace_id"] == root["trace_id"] == response.headers["X-Request-Id"]
    assert remote["parent_span_id"] == root["span_id"]
    assert remote["operation"] == "mcp.tool"
    assert root["operation"] == "http.server"
    assert "not-in-trace" not in output.getvalue()
    assert "sensitive-tool-arguments" not in output.getvalue()
    assert "private" not in output.getvalue()
