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
  type TextMessagePartProps,
  type ToolCallMessagePartProps,
  useAuiState,
} from "@assistant-ui/react";
import {
  fromAgUiMessages,
  useAgUiRuntime,
  type AgUiInterrupt,
} from "@assistant-ui/react-ag-ui";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";

import type { AgentRun } from "@/contracts";
import { Markdown } from "@/shared/ui";

import { restoreInterruptMetadata } from "./_history";
import styles from "./agent-ui.module.css";

const OpenVirtualFileContext = createContext<(path: string) => void>(() => {});

function TextPart({ text }: TextMessagePartProps) {
  const openVirtualFile = useContext(OpenVirtualFileContext);
  return <Markdown onOpenVirtualFile={openVirtualFile} text={text} />;
}

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

  if (waitingForDecision) {
    const label =
      toolName === "write_file" || toolName === "edit_file"
        ? "Approve Project File change"
        : "Approve protected action";

    return (
      <section aria-label={label} className={styles.approvalCard}>
        <strong>{label}</strong>
        <p>Agent Hub will continue automatically after your decision.</p>
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
      </section>
    );
  }

  return (
    <section className={styles.toolCall}>
      <strong>{toolName}</strong>
      <pre>{JSON.stringify(args, null, 2)}</pre>
      {result !== undefined ? <p>{String(result)}</p> : null}
    </section>
  );
}

function Message() {
  const role = useAuiState((state) => state.message.role);
  const isUser = role === "user";

  return (
    <MessagePrimitive.Root
      aria-label={isUser ? "You" : "Agent Hub"}
      className={`${styles.message} ${isUser ? styles.userMessage : styles.assistantMessage}`}
      data-role={role}
    >
      <span className={styles.messageAuthor}>
        {isUser ? "You" : "Agent Hub"}
      </span>
      <MessagePrimitive.Parts
        components={{ Text: TextPart, tools: { Fallback: ToolCall } }}
      />
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

    async function loadLatestRun(attempt: number) {
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
          attempt < 2 &&
          (latest?.status === "queued" ||
            latest?.status === "running" ||
            latest?.status === "cancelling")
        ) {
          refreshTimer = setTimeout(
            () => void loadLatestRun(attempt + 1),
            attempt === 0 ? 500 : 1500,
          );
        }
      } catch {
        if (active) setLatestRun(null);
      }
    }

    if (!isRunning) void loadLatestRun(0);
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
      {!isRunning && latestRun?.error ? (
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
      const body = (await response.json()) as {
        interrupts?: AgUiInterrupt[];
        messages?: unknown[];
      };
      const interrupts = body.interrupts ?? [];
      const restored = restoreInterruptMetadata(
        body.messages ?? [],
        interrupts,
      );
      const converted = fromAgUiMessages(restored.messages);
      const messages = converted.map((message) =>
        fromThreadMessageLike(
          message,
          generateId(),
          message.id === restored.interruptedMessageId
            ? { reason: "interrupt", type: "requires-action" }
            : { reason: "unknown", type: "complete" },
        ),
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
  onOpenVirtualFile,
  onUserMessage,
  projectId,
  threadId,
}: {
  onOpenVirtualFile: (path: string) => void;
  onUserMessage?: (message: string) => void;
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

  function captureUserMessage(event: FormEvent<HTMLFormElement>) {
    const input = event.currentTarget.querySelector("textarea");
    const message = input?.value ?? "";
    if (message.trim()) onUserMessage?.(message);
  }

  return (
    <OpenVirtualFileContext.Provider value={onOpenVirtualFile}>
      <AssistantRuntimeProvider runtime={runtime}>
        <ThreadPrimitive.Root className={styles.thread}>
          <ThreadPrimitive.Viewport className={styles.viewport}>
            <ThreadPrimitive.Empty>
              <div className={styles.empty}>
                <p className={styles.eyebrow}>Agent Hub</p>
                <h1>What are we working on?</h1>
                <p>
                  This Thread keeps its own conversation state within the
                  Project.
                </p>
              </div>
            </ThreadPrimitive.Empty>
            <ThreadPrimitive.Messages components={{ Message }} />
            <RunStatus runsUrl={runsUrl} />
            {error ? <p className={styles.runError}>{error}</p> : null}
            <ThreadPrimitive.ViewportFooter className={styles.footer}>
              <ComposerPrimitive.Root
                className={styles.composer}
                onSubmit={captureUserMessage}
              >
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
    </OpenVirtualFileContext.Provider>
  );
}
