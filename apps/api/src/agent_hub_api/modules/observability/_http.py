"""Request correlation and payload-free access logging for the API boundary."""

import json
import logging
import sys
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agent_hub_api.modules.observability._metrics import MetricsRegistry

logger = logging.getLogger("agent_hub_api.requests")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp, *, metrics: MetricsRegistry | None = None) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = monotonic()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id.encode("ascii")),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            route = scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            duration_seconds = monotonic() - started
            if self.metrics is not None and route_path != "/metrics":
                self.metrics.observe(scope["method"], route_path, status_code, duration_seconds)
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": scope["method"],
                        "route": route_path,
                        "status": status_code,
                        "duration_ms": round(duration_seconds * 1000),
                    },
                    separators=(",", ":"),
                )
            )


def create_metrics_router(metrics: MetricsRegistry) -> APIRouter:
    router = APIRouter()

    @router.get("/metrics", include_in_schema=False)
    async def scrape() -> PlainTextResponse:
        return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    return router
