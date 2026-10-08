"""Local OpenAI-compatible scripted model for the foundation acceptance flow."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if not request.get("stream"):
            self.send_error(400, "The acceptance model requires streaming")
            return
        messages = request["messages"]
        command_index = next(
            (
                index
                for index in range(len(messages) - 1, -1, -1)
                if messages[index]["role"] == "user"
                and str(messages[index].get("content", "")).startswith("foundation:")
            ),
            -1,
        )
        command = messages[command_index].get("content", "") if command_index >= 0 else ""
        tool_results = [
            message for message in messages[command_index + 1 :] if message["role"] == "tool"
        ]
        if command == "foundation:notice" and not any(
            str(message.get("content", "")).startswith("[System Notification]:")
            and "Bridge status (" in str(message.get("content", ""))
            and "v2)" in str(message.get("content", ""))
            for message in messages[command_index + 1 :]
        ):
            self.send_error(400, "The Project change notice was not supplied")
            return
        tool_call: tuple[str, dict[str, object]] | None = None
        if not tool_results and command == "foundation:status":
            tool_call = ("foundation_fixture__foundation_status", {})
        if not tool_results and command == "foundation:write-file":
            tool_call = (
                "write_file",
                {
                    "file_path": "/project/foundation-note.md",
                    "content": "Shared foundation note.\n",
                },
            )
        if not tool_results and command == "foundation:read-file":
            tool_call = (
                "read_file",
                {"file_path": "/project/foundation-note.md"},
            )
        if not tool_results and command == "foundation:create-artifact":
            tool_call = (
                "create_project_artifact",
                {
                    "plugin_id": "foundation-fixture",
                    "tool_name": "create_status_artifact",
                    "arguments_json": '{"title":"Bridge status"}',
                },
            )
        if command == "foundation:edit-artifact":
            if not tool_results:
                if any(
                    "Bridge status" in str(message.get("content", ""))
                    for message in messages
                    if message["role"] == "system"
                ):
                    self.send_error(400, "Artifact contents leaked into the system prompt")
                    return
                tool_call = ("discover_project_artifacts", {})
            elif len(tool_results) == 1:
                summaries = json.loads(tool_results[-1]["content"])
                artifact = next(item for item in summaries if item["title"] == "Bridge status")
                tool_call = ("load_project_artifact", {"artifact_id": artifact["id"]})
            elif len(tool_results) == 2:
                document = json.loads(tool_results[-1]["content"])
                tool_call = (
                    "edit_project_artifact",
                    {
                        "artifact_id": document["artifact"]["id"],
                        "expected_version": document["artifact"]["documentVersion"],
                        "tool_name": "set_status_artifact_status",
                        "arguments_json": '{"status":"unavailable"}',
                    },
                )
        if tool_results:
            latest_result = str(tool_results[-1]["content"])
            required_result = {
                "foundation:write-file": "/project/foundation-note.md",
                "foundation:read-file": "Shared foundation note.",
                "foundation:create-artifact": "Created Artifact Bridge status",
                "foundation:edit-artifact": (
                    "Updated Artifact Bridge status" if len(tool_results) == 3 else None
                ),
            }.get(command)
            if required_result is not None and required_result not in latest_result:
                self.send_error(400, f"Unexpected result for {command}")
                return
            if command == "foundation:status" and (
                json.loads(latest_result).get("status") != "available"
            ):
                self.send_error(400, "Fixture status was not available")
                return
        if tool_call is not None:
            name, arguments = tool_call
            available_tools = {tool["function"]["name"] for tool in request.get("tools", [])}
            if name not in available_tools:
                self.send_error(400, f"Expected tool {name} is unavailable")
                return
            deltas = [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": f"foundation-{name}-call",
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                },
                {},
            ]
            finish_reason = "tool_calls"
        else:
            answer = {
                "foundation:status": "Fixture status is available.",
                "foundation:write-file": "Shared foundation note saved.",
                "foundation:read-file": "Second Thread read Shared foundation note.",
                "foundation:create-artifact": "Bridge status Artifact created.",
                "foundation:edit-artifact": "Bridge status Artifact updated.",
                "foundation:notice": "Project change notice received.",
            }.get(command, "Foundation ready.")
            deltas = [{"role": "assistant", "content": answer}, {}]
            finish_reason = "stop"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for index, delta in enumerate(deltas):
            event = {
                "id": "foundation-fixture-response",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "foundation-script",
                "choices": [
                    {
                        "index": 0,
                        "delta": delta,
                        "finish_reason": finish_reason if index == len(deltas) - 1 else None,
                    }
                ],
            }
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, _format: str, *_args: object) -> None:
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8012), Handler).serve_forever()
