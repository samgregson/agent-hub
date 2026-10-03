"""Bound request bodies before FastAPI parses or forwards them."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_MAX_BODY_FRAMES = 1_024


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return

        content_lengths = [
            value for name, value in scope.get("headers", []) if name.lower() == b"content-length"
        ]
        if len(content_lengths) > 1:
            await _reject(send, 400, b'{"detail":"Invalid Content-Length"}')
            return
        if content_lengths:
            try:
                declared_bytes = int(content_lengths[0])
            except ValueError:
                await _reject(send, 400, b'{"detail":"Invalid Content-Length"}')
                return
            if declared_bytes < 0:
                await _reject(send, 400, b'{"detail":"Invalid Content-Length"}')
                return
            if declared_bytes > self.max_bytes:
                await _reject(send, 413, b'{"detail":"Request body exceeds the size limit"}')
                return

        body = bytearray()
        frame_count = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            frame_count += 1
            chunk = message.get("body", b"")
            if frame_count > _MAX_BODY_FRAMES or len(body) + len(chunk) > self.max_bytes:
                await _reject(send, 413, b'{"detail":"Request body exceeds the size limit"}')
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def _reject(send: Send, status: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
