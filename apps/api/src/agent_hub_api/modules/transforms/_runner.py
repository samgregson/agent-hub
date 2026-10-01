"""Bounded internal HTTP adapter for the isolated Deno/Pyodide runner."""

import asyncio
import json
from http.client import HTTPConnection
from urllib.parse import urlsplit

from agent_hub_api.modules.transforms._application import TransformExecutionError


class DenoTransformRunner:
    def __init__(self, url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Transform runner URL must be an internal HTTP address")
        self._host = parsed.hostname
        self._port = parsed.port or 80
        self._path = f"{parsed.path.rstrip('/')}/execute"

    async def execute(
        self, source: str, inputs: dict[str, object], parameters: dict[str, object]
    ) -> tuple[object, str]:
        return await asyncio.to_thread(self._send, source, inputs, parameters)

    def _send(
        self, source: str, inputs: dict[str, object], parameters: dict[str, object]
    ) -> tuple[object, str]:
        payload = json.dumps(
            {"source": source, "inputs": inputs, "parameters": parameters},
            allow_nan=False,
        ).encode()
        if len(payload) > 128_000:
            raise TransformExecutionError("input_limit")
        connection = HTTPConnection(self._host, self._port, timeout=12)
        try:
            connection.request(
                "POST",
                self._path,
                body=payload,
                headers={"content-type": "application/json"},
            )
            response = connection.getresponse()
            raw = response.read(130_001)
            if len(raw) > 130_000:
                raise TransformExecutionError("output_limit")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise TransformExecutionError("runner_failed")
            if response.status != 200 or result.get("ok") is not True:
                code = result.get("code")
                raise TransformExecutionError(code if isinstance(code, str) else "runner_failed")
            runtime = result.get("pyodide")
            if not isinstance(runtime, str) or "output" not in result:
                raise TransformExecutionError("runner_failed")
            return result["output"], f"pyodide:{runtime}"
        except (OSError, TimeoutError, ValueError) as error:
            raise TransformExecutionError("runner_unavailable") from error
        finally:
            connection.close()
