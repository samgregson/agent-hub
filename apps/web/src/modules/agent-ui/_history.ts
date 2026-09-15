import type { AgUiInterrupt } from "@assistant-ui/react-ag-ui";

interface RestoredHistory {
  interruptedMessageId: string | null;
  messages: unknown[];
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
