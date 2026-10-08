"""Payload-free, correlated spans for the API and remote Plugin boundary."""

import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from time import monotonic
from uuid import uuid4

trace_logger = logging.getLogger("agent_hub_api.traces")
trace_logger.setLevel(logging.INFO)
trace_logger.propagate = False
if not trace_logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    trace_logger.addHandler(handler)

_trace_context: ContextVar[tuple[str, str] | None] = ContextVar(
    "agent_hub_trace_context", default=None
)


def begin_request_trace(request_id: str) -> tuple[Token[tuple[str, str] | None], str]:
    span_id = uuid4().hex[:16]
    return _trace_context.set((request_id, span_id)), span_id


def end_request_trace(
    token: Token[tuple[str, str] | None],
    *,
    request_id: str,
    span_id: str,
    route: str,
    method: str,
    status: int,
    duration_seconds: float,
) -> None:
    trace_logger.info(
        json.dumps(
            {
                "event": "trace_span",
                "trace_id": request_id,
                "span_id": span_id,
                "parent_span_id": None,
                "operation": "http.server",
                "route": route,
                "method": method,
                "status": status,
                "duration_ms": round(duration_seconds * 1000),
            },
            separators=(",", ":"),
        )
    )
    _trace_context.reset(token)


@asynccontextmanager
async def trace_plugin_operation(operation: str, plugin_id: str) -> AsyncIterator[None]:
    parent = _trace_context.get()
    span_id = uuid4().hex[:16]
    started = monotonic()
    outcome = "ok"
    try:
        yield
    except BaseException:
        outcome = "error"
        raise
    finally:
        if parent is not None:
            trace_logger.info(
                json.dumps(
                    {
                        "event": "trace_span",
                        "trace_id": parent[0],
                        "span_id": span_id,
                        "parent_span_id": parent[1],
                        "operation": operation,
                        "plugin_id": plugin_id,
                        "outcome": outcome,
                        "duration_ms": round((monotonic() - started) * 1000),
                    },
                    separators=(",", ":"),
                )
            )
