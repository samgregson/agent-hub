"""Bounded internal HTTP adapter for the isolated Deno/Pyodide runner."""

import asyncio
import json
from http.client import HTTPConnection
from urllib.parse import urlsplit

from agent_hub_api.modules.functions._application import (
    FunctionExecutionError,
    FunctionRuntimeIdentity,
)


class DenoFunctionRunner:
    def __init__(self, url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Function runner URL must be an internal HTTP address")
        self._host = parsed.hostname
        self._port = parsed.port or 80
        self._path = f"{parsed.path.rstrip('/')}/execute"

    async def identity(self) -> FunctionRuntimeIdentity:
        return await asyncio.to_thread(self._identity)

    def _identity(self) -> FunctionRuntimeIdentity:
        connection = HTTPConnection(self._host, self._port, timeout=4)
        try:
            connection.request("GET", self._path.removesuffix("/execute") + "/runtime")
            response = connection.getresponse()
            raw = response.read(2049)
            if response.status != 200 or len(raw) > 2048:
                raise FunctionExecutionError("runner_unavailable")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise FunctionExecutionError("runner_failed")
            deno, pyodide, package_hash, limits = (
                payload.get("deno"),
                payload.get("pyodide"),
                payload.get("packageHash"),
                payload.get("limits"),
            )
            if (
                not isinstance(deno, str)
                or not isinstance(pyodide, str)
                or not isinstance(package_hash, str)
                or len(package_hash) != 64
                or not isinstance(limits, dict)
                or any(
                    not isinstance(limits.get(key), int) or limits[key] < 1
                    for key in (
                        "timeoutMs",
                        "maxInputBytes",
                        "maxOutputBytes",
                        "maxSourceBytes",
                        "maxConcurrent",
                    )
                )
            ):
                raise FunctionExecutionError("runner_failed")
            return FunctionRuntimeIdentity(f"deno:{deno};pyodide:{pyodide}", package_hash, limits)
        except (OSError, TimeoutError, ValueError) as error:
            raise FunctionExecutionError("runner_unavailable") from error
        finally:
            connection.close()

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
            raise FunctionExecutionError("input_limit")
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
                raise FunctionExecutionError("output_limit")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise FunctionExecutionError("runner_failed")
            if response.status != 200 or result.get("ok") is not True:
                code = result.get("code")
                raise FunctionExecutionError(code if isinstance(code, str) else "runner_failed")
            deno, pyodide = result.get("deno"), result.get("pyodide")
            if not isinstance(deno, str) or not isinstance(pyodide, str) or "output" not in result:
                raise FunctionExecutionError("runner_failed")
            return result["output"], f"deno:{deno};pyodide:{pyodide}"
        except (OSError, TimeoutError, ValueError) as error:
            raise FunctionExecutionError("runner_unavailable") from error
        finally:
            connection.close()
