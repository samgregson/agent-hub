import assert from "node:assert/strict";
import test from "node:test";

import { fromAgUiMessages } from "@assistant-ui/react-ag-ui";

import { restoreInterruptMetadata, restoreResolvedApprovals } from "./_history";

test("restores pending interrupts onto the last assistant message", () => {
  const result = restoreInterruptMetadata(
    [
      { content: "first", id: "assistant-1", role: "assistant" },
      { content: "question", id: "user-1", role: "user" },
      {
        content: null,
        id: "assistant-2",
        metadata: { custom: { existing: true } },
        role: "assistant",
      },
    ],
    [{ id: "interrupt-1", reason: "tool_call", toolCallId: "tool-1" }],
  );

  assert.equal(result.interruptedMessageId, "assistant-2");
  assert.deepEqual(result.messages[2], {
    content: null,
    id: "assistant-2",
    metadata: {
      custom: {
        agui: {
          interrupts: [
            {
              id: "interrupt-1",
              reason: "tool_call",
              toolCallId: "tool-1",
            },
          ],
        },
        existing: true,
      },
    },
    role: "assistant",
  });
});

test("does not make history actionable when no interrupts are pending", () => {
  const messages = [{ content: "done", id: "assistant-1", role: "assistant" }];

  const result = restoreInterruptMetadata(messages, []);

  assert.equal(result.interruptedMessageId, null);
  assert.deepEqual(result.messages, messages);
  assert.notEqual(result.messages, messages);
});

test("restored interrupt becomes an assistant-ui tool approval", () => {
  const restored = restoreInterruptMetadata(
    [
      {
        content: null,
        id: "assistant-1",
        role: "assistant",
        toolCalls: [
          {
            function: {
              arguments: '{"note":"test"}',
              name: "foundation_protected_action",
            },
            id: "tool-1",
            type: "function",
          },
        ],
      },
    ],
    [{ id: "interrupt-1", reason: "tool_call", toolCallId: "tool-1" }],
  );

  const [message] = fromAgUiMessages(restored.messages);

  assert.equal(message.role, "assistant");
  assert.deepEqual(message.content, [
    {
      args: { note: "test" },
      argsText: '{"note":"test"}',
      approval: { id: "interrupt-1" },
      toolCallId: "tool-1",
      toolName: "foundation_protected_action",
      type: "tool-call",
    },
  ]);
});

test("restores a resolved decision only onto its original tool call", () => {
  const converted = fromAgUiMessages([
    {
      content: null,
      id: "assistant-1",
      role: "assistant",
      toolCalls: [
        {
          function: {
            arguments: '{"file_path":"/project/a.md"}',
            name: "write_file",
          },
          id: "tool-1",
          type: "function",
        },
        {
          function: { arguments: "{}", name: "foundation_status" },
          id: "tool-2",
          type: "function",
        },
      ],
    },
  ]);
  const [restored] = restoreResolvedApprovals(converted, [
    {
      approved: false,
      decisionRunId: "run-2",
      interruptId: "interrupt-1",
      resolution: null,
      sourceRunId: "run-1",
      toolCallId: "tool-1",
    },
  ]);

  assert.equal(restored.role, "assistant");
  if (restored.role !== "assistant") return;
  assert.deepEqual(restored.content[0], {
    ...(converted[0].content[0] as Record<string, unknown>),
    approval: { id: "interrupt-1", approved: false },
  });
  assert.deepEqual(restored.content[1], converted[0].content[1]);
});
