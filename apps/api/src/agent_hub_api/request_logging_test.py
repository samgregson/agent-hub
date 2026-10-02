import io
import json
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route

from agent_hub_api.main import create_app
from agent_hub_api.modules.observability._http import RequestLoggingMiddleware, logger
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
