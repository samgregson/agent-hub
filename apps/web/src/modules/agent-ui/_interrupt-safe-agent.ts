import {
  HttpAgent,
  type AgentSubscriber,
  type Message,
  type RunAgentResult,
} from "@ag-ui/client";

function hasUnresolvedToolCall(
  message: Message,
  unresolvedToolCallIds: ReadonlySet<string>,
): boolean {
  return (
    message.role === "assistant" &&
    (message.toolCalls ?? []).some((toolCall) =>
      unresolvedToolCallIds.has(toolCall.id),
    )
  );
}

/** Keep checkpoint snapshots from replacing the live, interruptable tool call. */
export class InterruptSafeHttpAgent extends HttpAgent {
  override runAgent(
    parameters?: Parameters<HttpAgent["runAgent"]>[0],
    subscriber?: AgentSubscriber,
  ): Promise<RunAgentResult> {
    if (!subscriber) return super.runAgent(parameters, subscriber);

    const unresolvedToolCallIds = new Set<string>();
    const wrappedSubscriber: AgentSubscriber = {
      ...subscriber,
      onToolCallStartEvent: (params) => {
        unresolvedToolCallIds.add(params.event.toolCallId);
        return subscriber.onToolCallStartEvent?.(params);
      },
      onToolCallResultEvent: (params) => {
        unresolvedToolCallIds.delete(params.event.toolCallId);
        return subscriber.onToolCallResultEvent?.(params);
      },
      onMessagesSnapshotEvent: (params) => {
        const messages = params.event.messages.filter(
          (message) => !hasUnresolvedToolCall(message, unresolvedToolCallIds),
        );
        return subscriber.onMessagesSnapshotEvent?.({
          ...params,
          event: { ...params.event, messages },
        });
      },
    };

    return super.runAgent(parameters, wrappedSubscriber);
  }
}
