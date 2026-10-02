import type { AgUiInterrupt } from "@assistant-ui/react-ag-ui";

interface RestoredHistory {
  interruptedMessageId: string | null;
  messages: unknown[];
}

export interface ResolvedApproval {
  approved: boolean | null;
  decisionRunId: string;
  interruptId: string;
  resolution: "cancelled" | "expired" | null;
  sourceRunId: string | null;
  toolCallId: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function restoreInterruptMetadata(
  sourceMessages: unknown[],
  interrupts: AgUiInterrupt[],
): RestoredHistory {
  const messages = sourceMessages.map((message) =>
    isRecord(message) ? { ...message } : message,
  );
  if (!interrupts.length) {
    return { interruptedMessageId: null, messages };
  }

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!isRecord(message) || message.role !== "assistant") continue;

    const metadata = isRecord(message.metadata) ? message.metadata : {};
    const custom = isRecord(metadata.custom) ? metadata.custom : {};
    const agui = isRecord(custom.agui) ? custom.agui : {};
    messages[index] = {
      ...message,
      metadata: {
        ...metadata,
        custom: {
          ...custom,
          agui: { ...agui, interrupts },
        },
      },
    };
    return {
      interruptedMessageId: typeof message.id === "string" ? message.id : null,
      messages,
    };
  }

  return { interruptedMessageId: null, messages };
}

export function restoreResolvedApprovals<
  T extends { content?: unknown; role: string },
>(sourceMessages: T[], decisions: ResolvedApproval[]): T[] {
  const byToolCall = new Map(
    decisions.map((decision) => [decision.toolCallId, decision]),
  );
  return sourceMessages.map((message) => {
    if (message.role !== "assistant" || !Array.isArray(message.content))
      return message;
    const content = message.content.map((part: unknown) => {
      if (!isRecord(part) || part.type !== "tool-call") return part;
      const decision = byToolCall.get(String(part.toolCallId));
      if (!decision) return part;
      return {
        ...part,
        approval: {
          id: decision.interruptId,
          ...(decision.approved === null
            ? {}
            : { approved: decision.approved }),
          ...(decision.resolution ? { resolution: decision.resolution } : {}),
        },
      };
    });
    return { ...message, content };
  });
}
