"use client";

import { HttpAgent } from "@ag-ui/client";
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  fromThreadMessageLike,
  generateId,
  MessagePrimitive,
  ThreadPrimitive,
  type ThreadHistoryAdapter,
  type ToolCallMessagePartProps,
  useAuiState,
} from "@assistant-ui/react";
import { fromAgUiMessages, useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import { useEffect, useMemo, useState } from "react";

import type { AgentRun } from "@/contracts";

import styles from "./agent-ui.module.css";

function ToolCall({
  args,
  approval,
  result,
  respondToApproval,
  toolName,
}: ToolCallMessagePartProps) {
  const waitingForDecision =
    approval !== undefined &&
    approval.approved === undefined &&
    approval.resolution === undefined;

  return (
    <section className={styles.toolCall}>
      <strong>{toolName}</strong>
      <pre>{JSON.stringify(args, null, 2)}</pre>
      {waitingForDecision ? (
        <div className={styles.approvalActions}>
          <button
            onClick={() => respondToApproval?.({ approved: true })}
            type="button"
          >
            Approve
          </button>
          <button
            onClick={() =>
              respondToApproval?.({
                approved: false,
                reason: "Rejected by the user",
              })
            }
            type="button"
          >
            Reject
          </button>
        </div>
      ) : null}
      {result !== undefined ? <p>{String(result)}</p> : null}
    </section>
  );
}

function Message() {
  return (
    <MessagePrimitive.Root className={styles.message}>
      <MessagePrimitive.Parts components={{ tools: { Fallback: ToolCall } }} />
      <span className={styles.messageError}>
        <MessagePrimitive.Error />
      </span>
    </MessagePrimitive.Root>
  );
}

function RunStatus({ runsUrl }: { runsUrl: string }) {
  const isRunning = useAuiState((state) => state.thread.isRunning);
  const [latestRun, setLatestRun] = useState<AgentRun | null>(null);

  useEffect(() => {
    let active = true;
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;

    async function loadLatestRun() {
      try {
        const response = await fetch(runsUrl, { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`Run status failed with status ${response.status}`);
        }
        const runs = (await response.json()) as AgentRun[];
        const latest = runs[0] ?? null;
        if (!active) return;
        setLatestRun(latest);
        if (
          isRunning ||
          latest?.status === "queued" ||
          latest?.status === "running" ||
          latest?.status === "cancelling"
        ) {
          refreshTimer = setTimeout(loadLatestRun, 750);
        }
      } catch {
        if (active) setLatestRun(null);
      }
    }

    void loadLatestRun();
    return () => {
      active = false;
      if (refreshTimer) clearTimeout(refreshTimer);
    };
  }, [isRunning, runsUrl]);

  const status = isRunning ? "running" : latestRun?.status;
  if (!status) return null;

  return (
    <div aria-live="polite" className={styles.runStatus}>
      <span>Run: {status}</span>
      {latestRun?.error ? (
        <span className={styles.runFailure}>{latestRun.error.message}</span>
      ) : null}
    </div>
  );
}

function createHistoryAdapter(
  projectId: string,
  threadId: string,
): ThreadHistoryAdapter {
  return {
    append: async () => {},
    load: async () => {
      const response = await fetch(
        `/api/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(threadId)}/history`,
        { cache: "no-store" },
      );
      if (!response.ok) {
        throw new Error(`Thread history failed with status ${response.status}`);
      }
      const body = (await response.json()) as { messages?: unknown[] };
      const messages = fromAgUiMessages(body.messages ?? []).map((message) =>
        fromThreadMessageLike(message, generateId(), {
          reason: "unknown",
          type: "complete",
        }),
      );
      let parentId: string | null = null;
      const repository = messages.map((message) => {
        const item = { message, parentId };
        parentId = message.id;
        return item;
      });
      return { headId: parentId, messages: repository };
    },
  };
}

export function AgentChat({
  projectId,
  threadId,
}: {
  projectId: string;
  threadId: string;
}) {
  const [error, setError] = useState<string | null>(null);
  const agent = useMemo(
    () =>
      new HttpAgent({
        threadId,
        url: `/api/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(threadId)}/agent`,
      }),
    [projectId, threadId],
  );
  const history = useMemo(
    () => createHistoryAdapter(projectId, threadId),
    [projectId, threadId],
  );
  const runtime = useAgUiRuntime({
    adapters: { history },
    agent,
    onError: () => setError("The agent run failed. You can try sending again."),
  });
  const runsUrl = `/api/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(threadId)}/runs`;

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className={styles.thread}>
        <ThreadPrimitive.Viewport className={styles.viewport}>
          <ThreadPrimitive.Empty>
            <div className={styles.empty}>
              <p className={styles.eyebrow}>Agent Hub</p>
              <h1>What are we working on?</h1>
              <p>
                This Thread keeps its own conversation state within the Project.
              </p>
            </div>
          </ThreadPrimitive.Empty>
          <ThreadPrimitive.Messages components={{ Message }} />
          <RunStatus runsUrl={runsUrl} />
          {error ? <p className={styles.runError}>{error}</p> : null}
          <ThreadPrimitive.ViewportFooter className={styles.footer}>
            <ComposerPrimitive.Root className={styles.composer}>
              <ComposerPrimitive.Input
                aria-label="Message Agent Hub"
                className={styles.input}
                placeholder="Ask Agent Hub…"
                rows={2}
              />
              <div className={styles.actions}>
                <ComposerPrimitive.Cancel className={styles.cancel}>
                  Stop
                </ComposerPrimitive.Cancel>
                <ComposerPrimitive.Send className={styles.send}>
                  Send
                </ComposerPrimitive.Send>
              </div>
            </ComposerPrimitive.Root>
          </ThreadPrimitive.ViewportFooter>
        </ThreadPrimitive.Viewport>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
