"use client";

import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  fromThreadMessageLike,
  generateId,
  MessagePrimitive,
  ThreadPrimitive,
  useAui,
  type ThreadHistoryAdapter,
  type ToolCallMessagePartProps,
  useAuiState,
} from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import {
  fromAgUiMessages,
  useAgUiRuntime,
  type AgUiInterrupt,
} from "@assistant-ui/react-ag-ui";
import remarkGfm from "remark-gfm";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ComponentProps,
  type FormEvent,
} from "react";

import type { AgentRun } from "@/contracts";

import {
  restoreInterruptMetadata,
  restoreResolvedApprovals,
  type ResolvedApproval,
} from "./_history";
import {
  approvalLabel,
  approvalTarget,
  isApprovalOnlyTool,
  proposedFileContent,
  resolvedApprovalReview,
  unifiedFileDiff,
  type ProposedFileReview,
} from "./_approval";
import { shouldClearTransientRunError } from "./_run-state";
import { InterruptSafeHttpAgent } from "./_interrupt-safe-agent";
import styles from "./agent-ui.module.css";

const OpenVirtualFileContext = createContext<(path: string) => void>(() => {});
const OpenArtifactContext = createContext<(artifactId: string) => void>(
  () => {},
);
const OpenFileProposalContext = createContext<
  (proposal: ProposedFileReview) => void
>(() => {});
const ProjectIdContext = createContext("");
const ApprovalHistoryContext = createContext<Record<string, ResolvedApproval>>(
  {},
);

function virtualFilePath(url: string): string | null {
  const path = url.startsWith("sandbox:/") ? url.replace(/^sandbox:/, "") : url;
  return /^\/(?:project|scratch)\//.test(path) &&
    !path.split("/").includes("..")
    ? path
    : null;
}

function safeMarkdownUrl(url: string): string {
  if (virtualFilePath(url)) return url;
  return safeExternalMarkdownUrl(url) ?? "";
}

function safeExternalMarkdownUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:"
      ? url
      : null;
  } catch {
    return null;
  }
}

function MarkdownAnchor({ children, href, ...props }: ComponentProps<"a">) {
  const openVirtualFile = useContext(OpenVirtualFileContext);
  const path = href ? virtualFilePath(href) : null;
  if (path) {
    return (
      <button
        className={styles.markdownLinkButton}
        onClick={() => openVirtualFile(path)}
        type="button"
      >
        {children}
      </button>
    );
  }

  const safeHref = href ? safeExternalMarkdownUrl(href) : null;
  if (safeHref) {
    return (
      <a {...props} href={safeHref} rel="noreferrer" target="_blank">
        {children}
      </a>
    );
  }
  return <>{children}</>;
}

function MarkdownTable({ children, ...props }: ComponentProps<"table">) {
  return (
    <div
      aria-label="Message table"
      className={styles.markdownTable}
      role="region"
      tabIndex={0}
    >
      <table {...props}>{children}</table>
    </div>
  );
}

const markdownComponents = { a: MarkdownAnchor, table: MarkdownTable };
const markdownPlugins = [remarkGfm];

function TextPart() {
  return (
    <MarkdownTextPrimitive
      className={styles.messageMarkdown}
      components={markdownComponents}
      remarkPlugins={markdownPlugins}
      urlTransform={safeMarkdownUrl}
    />
  );
}

function ToolCall({
  args,
  argsText,
  approval,
  dock = false,
  isError,
  result,
  respondToApproval,
  toolCallId,
  toolName,
}: ToolCallMessagePartProps & { dock?: boolean }) {
  const projectId = useContext(ProjectIdContext);
  const openVirtualFile = useContext(OpenVirtualFileContext);
  const openArtifact = useContext(OpenArtifactContext);
  const openFileProposal = useContext(OpenFileProposalContext);
  const decisionRecord = useContext(ApprovalHistoryContext)[toolCallId];
  const [review, setReview] = useState<
    | { kind: "loading" }
    | { kind: "unavailable"; text: string }
    | ProposedFileReview
    | null
  >(null);
  const [submitting, setSubmitting] = useState(false);
  const waitingForDecision =
    approval !== undefined &&
    approval.approved === undefined &&
    approval.resolution === undefined;

  useEffect(() => {
    const target = approvalTarget(args);
    if (!dock || !waitingForDecision || !target.path || !projectId) return;
    const path = target.path;
    const controller = new AbortController();
    let active = true;
    const url = `/api/projects/${encodeURIComponent(projectId)}/files?path=${encodeURIComponent(path)}`;
    void (async () => {
      setReview({ kind: "loading" });
      try {
        const response = await fetch(url, {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!active) return;
        if (response.status === 404) {
          const proposed = proposedFileContent(toolName, args, null);
          setReview(
            proposed === null
              ? {
                  kind: "unavailable",
                  text: "The proposed file could not be previewed.",
                }
              : { kind: "preview", path, proposed, text: proposed },
          );
          return;
        }
        if (!response.ok) throw new Error("File preview unavailable");
        const file = (await response.json()) as { content?: string };
        if (!active) return;
        const current = typeof file.content === "string" ? file.content : null;
        const proposed = proposedFileContent(toolName, args, current);
        setReview(
          current === null || proposed === null
            ? {
                kind: "unavailable",
                text: "The proposed change could not be previewed.",
              }
            : {
                kind: "diff",
                path,
                proposed,
                text: unifiedFileDiff(path, current, proposed),
              },
        );
      } catch {
        if (active) {
          setReview({
            kind: "unavailable",
            text: "File preview unavailable. Review the action details before deciding.",
          });
        }
      }
    })();
    return () => {
      active = false;
      controller.abort();
    };
  }, [args, argsText, dock, projectId, toolName, waitingForDecision]);

  if (approval) {
    if (waitingForDecision && !dock) return null;
    const label = approvalLabel(toolName);
    const target = approvalTarget(args);
    const outcome = waitingForDecision
      ? "Needs approval"
      : approval.resolution === "cancelled"
        ? "Cancelled"
        : approval.resolution === "expired"
          ? "Expired"
          : approval.approved === false
            ? "Rejected"
            : isError
              ? "Approved · action failed"
              : "Approved";

    return (
      <section aria-label={label} className={styles.approvalCard}>
        <div className={styles.approvalHeading}>
          <strong>
            {waitingForDecision ? label : label.replace(/^Approve /, "")}
          </strong>
          <span className={styles.approvalStatus}>{outcome}</span>
        </div>
        <p className={styles.approvalTarget}>{target.summary}</p>
        {approval.prompt ? <p>{approval.prompt}</p> : null}
        {waitingForDecision ? (
          <>
            {target.path ? (
              <>
                <details className={styles.approvalDetails}>
                  <summary>
                    {review?.kind === "preview"
                      ? "Preview new file"
                      : "Review proposed change"}
                  </summary>
                  {review?.kind === "loading" ? (
                    <p>Loading file preview…</p>
                  ) : null}
                  {review && "text" in review ? <pre>{review.text}</pre> : null}
                </details>
                {review?.kind === "diff" || review?.kind === "preview" ? (
                  <button
                    className={styles.approvalLink}
                    onClick={() => openFileProposal(review)}
                    type="button"
                  >
                    {review.kind === "diff"
                      ? "Open diff in preview"
                      : "Open proposed file in preview"}
                  </button>
                ) : null}
                <details className={styles.approvalDetails}>
                  <summary>Review action details</summary>
                  <pre>{JSON.stringify(args, null, 2)}</pre>
                </details>
              </>
            ) : (
              <details className={styles.approvalDetails}>
                <summary>Review action details</summary>
                <pre>{JSON.stringify(args, null, 2)}</pre>
              </details>
            )}
            <div className={styles.approvalActions}>
              <button
                disabled={submitting || !respondToApproval}
                onClick={() => {
                  setSubmitting(true);
                  void respondToApproval?.({ approved: true }).catch(() =>
                    setSubmitting(false),
                  );
                }}
                type="button"
              >
                Approve
              </button>
              <button
                disabled={submitting || !respondToApproval}
                onClick={() => {
                  setSubmitting(true);
                  void respondToApproval?.({
                    approved: false,
                    reason: "Rejected by the user",
                  }).catch(() => setSubmitting(false));
                }}
                type="button"
              >
                Reject
              </button>
            </div>
          </>
        ) : (
          <details className={styles.approvalDetails}>
            <summary>Review proposed change</summary>
            <pre>{resolvedApprovalReview(toolName, args)}</pre>
          </details>
        )}
        {approval.approved === true &&
        result !== undefined &&
        !isError &&
        target.path ? (
          <button
            className={styles.approvalLink}
            onClick={() => openVirtualFile(target.path!)}
            type="button"
          >
            Open Project File
          </button>
        ) : approval.approved === true &&
          result !== undefined &&
          !isError &&
          target.artifactId ? (
          <button
            className={styles.approvalLink}
            onClick={() => openArtifact(target.artifactId!)}
            type="button"
          >
            Open Artifact
          </button>
        ) : null}
        {decisionRecord ? (
          <details className={styles.approvalDetails}>
            <summary>Decision provenance</summary>
            <dl className={styles.approvalProvenance}>
              <dt>Interrupt</dt>
              <dd>{decisionRecord.interruptId}</dd>
              {decisionRecord.sourceRunId ? (
                <>
                  <dt>Request Run</dt>
                  <dd>{decisionRecord.sourceRunId}</dd>
                </>
              ) : null}
              <dt>Decision Run</dt>
              <dd>{decisionRecord.decisionRunId}</dd>
            </dl>
          </details>
        ) : null}
      </section>
    );
  }

  return null;
}

type ProcessCall = {
  args: unknown;
  argsText: string;
  approval?: ToolCallMessagePartProps["approval"];
  isError?: boolean;
  result?: unknown;
  status?: ToolCallMessagePartProps["status"];
  toolCallId: string;
  toolName: string;
};

function formatToolName(name: string) {
  return name
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatProcessValue(value: unknown) {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    return String(value);
  }
}

function ProcessEntry({ call }: { call: ProcessCall }) {
  const status = call.isError
    ? "Failed"
    : call.approval?.approved === false
      ? "Rejected"
      : call.approval?.approved === true
        ? "Approved"
        : call.result !== undefined
          ? "Completed"
          : call.status?.type === "running"
            ? "Running"
            : "Waiting";
  if (call.approval && call.approval.approved === undefined) return null;
  if (isApprovalOnlyTool(call.toolName)) return null;

  return (
    <details className={styles.processEntry}>
      <summary>
        <span>{formatToolName(call.toolName)}</span>
        <span className={styles.processEntryStatus}>{status}</span>
      </summary>
      <div className={styles.processEntryDetails}>
        {call.argsText ? (
          <div>
            <span className={styles.processFieldLabel}>Input</span>
            <pre>{call.argsText}</pre>
          </div>
        ) : null}
        {call.result !== undefined || call.status?.type === "running" ? (
          <div>
            <span className={styles.processFieldLabel}>
              {call.isError ? "Error" : "Output"}
            </span>
            <pre>
              {call.result === undefined
                ? "Waiting for output…"
                : formatProcessValue(call.result)}
            </pre>
          </div>
        ) : null}
        {call.approval?.reason ? <p>{call.approval.reason}</p> : null}
      </div>
    </details>
  );
}

function ProcessDisclosure({
  calls,
  running,
}: {
  calls: ProcessCall[];
  running: boolean;
}) {
  const visibleCalls = calls.filter(
    (call) =>
      !isApprovalOnlyTool(call.toolName) &&
      !(call.approval && call.approval.approved === undefined),
  );
  if (visibleCalls.length === 0 && !running) return null;
  const activeTool = visibleCalls.some(
    (call) => call.status?.type === "running",
  );

  return (
    <details className={styles.process} open={running}>
      <summary>
        <span className={running ? styles.processPulse : styles.processMark} />
        <span>{running ? "Thinking" : "Process"}</span>
        {running && activeTool ? (
          <span className={styles.processActivity}>Using tools</span>
        ) : null}
        {visibleCalls.length > 0 ? (
          <span className={styles.processCount}>
            {visibleCalls.length} {visibleCalls.length === 1 ? "step" : "steps"}
          </span>
        ) : null}
      </summary>
      {visibleCalls.length > 0 ? (
        <div className={styles.processEntries}>
          {visibleCalls.map((call) => (
            <ProcessEntry call={call} key={call.toolCallId} />
          ))}
        </div>
      ) : (
        <p className={styles.processWaiting}>
          The model is preparing its response.
        </p>
      )}
    </details>
  );
}

function Message() {
  const role = useAuiState((state) => state.message.role);
  const isUser = role === "user";

  return (
    <MessagePrimitive.Root
      className={`${styles.message} ${isUser ? styles.userMessage : styles.assistantMessage}`}
      data-role={role}
    >
      <MessagePrimitive.Parts
        components={{ Text: TextPart, tools: { Fallback: ToolCall } }}
      />
      <span className={styles.messageError}>
        <MessagePrimitive.Error />
      </span>
    </MessagePrimitive.Root>
  );
}

function ConversationMessages() {
  const messages = useAuiState((state) => state.thread.messages);
  const isRunning = useAuiState((state) => state.thread.isRunning);
  const turns = useMemo(() => {
    const result: Array<{
      indices: number[];
      calls: ProcessCall[];
      role: string;
    }> = [];
    let index = 0;
    while (index < messages.length) {
      const first = messages[index];
      const indices = [index];
      const calls: ProcessCall[] = [];
      if (first.role === "assistant") {
        let cursor = index;
        while (
          cursor < messages.length &&
          messages[cursor].role === "assistant"
        ) {
          indices.push(...(cursor === index ? [] : [cursor]));
          for (const part of messages[cursor].parts) {
            if (part.type === "tool-call") calls.push(part);
          }
          cursor += 1;
        }
        result.push({ indices, calls, role: "assistant" });
        index = cursor;
      } else {
        result.push({ indices, calls, role: first.role });
        index += 1;
      }
    }
    return result;
  }, [messages]);

  const visibleTurns =
    isRunning && turns.at(-1)?.role !== "assistant"
      ? [...turns, { indices: [], calls: [], role: "assistant" }]
      : turns;

  return (
    <>
      {visibleTurns.map((turn, turnIndex) => (
        <div
          className={styles.turn}
          key={messages[turn.indices[0]]?.id ?? "active-process"}
        >
          {turn.role === "assistant" ? (
            <ProcessDisclosure
              calls={turn.calls}
              running={isRunning && turnIndex === visibleTurns.length - 1}
            />
          ) : null}
          {turn.indices.map((messageIndex) => (
            <ThreadPrimitive.MessageByIndex
              components={{ Message }}
              index={messageIndex}
              key={messages[messageIndex]?.id}
            />
          ))}
        </div>
      ))}
    </>
  );
}

function ApprovalDock() {
  const aui = useAui();
  const messages = useAuiState((state) => state.thread.messages);
  const approvals = useMemo(
    () =>
      messages.flatMap((message) =>
        message.parts.flatMap((part) => {
          if (
            part.type !== "tool-call" ||
            !part.approval ||
            part.approval.approved !== undefined
          ) {
            return [];
          }
          return [{ messageId: message.id, part }];
        }),
      ),
    [messages],
  );
  if (approvals.length === 0) return null;

  return (
    <section aria-label="Pending approvals" className={styles.approvalDock}>
      {approvals.map(({ messageId, part }) => (
        <ToolCall
          {...part}
          dock
          key={part.toolCallId}
          addResult={(result) =>
            aui.thread
              .message({ id: messageId })
              .part({ toolCallId: part.toolCallId })
              .addToolResult(result)
          }
          resume={(payload) =>
            aui.thread
              .message({ id: messageId })
              .part({ toolCallId: part.toolCallId })
              .resumeToolCall(payload)
          }
          respondToApproval={(response) =>
            aui.thread
              .message({ id: messageId })
              .part({ toolCallId: part.toolCallId })
              .respondToToolApproval(response)
          }
        />
      ))}
    </section>
  );
}

function ComposerArea({
  onSubmit,
}: {
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const messages = useAuiState((state) => state.thread.messages);
  const hasPendingApproval = messages.some((message) =>
    message.parts.some(
      (part) =>
        part.type === "tool-call" &&
        part.approval !== undefined &&
        part.approval.approved === undefined &&
        part.approval.resolution === undefined,
    ),
  );

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    if (hasPendingApproval) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    onSubmit(event);
  }

  return (
    <>
      <ApprovalDock />
      {hasPendingApproval ? (
        <p className={styles.approvalHold} role="status">
          Respond to the pending approval before sending another message.
        </p>
      ) : null}
      <ComposerPrimitive.Root
        className={styles.composer}
        onSubmit={handleSubmit}
      >
        <ComposerPrimitive.Input
          aria-label="Message"
          className={styles.input}
          placeholder="Ask a question or describe a task…"
          rows={2}
        />
        <div className={styles.actions}>
          <ComposerPrimitive.Cancel className={styles.cancel}>
            Stop
          </ComposerPrimitive.Cancel>
          <ComposerPrimitive.Send
            className={styles.send}
            data-pending-approval={hasPendingApproval || undefined}
            disabled={hasPendingApproval}
          >
            Send
          </ComposerPrimitive.Send>
        </div>
      </ComposerPrimitive.Root>
    </>
  );
}

function RunStatus({
  onSuccessfulRun,
  runsUrl,
}: {
  onSuccessfulRun: () => void;
  runsUrl: string;
}) {
  const isRunning = useAuiState((state) => state.thread.isRunning);
  const messages = useAuiState((state) => state.thread.messages);
  const hasPendingApproval = messages.some((message) =>
    message.parts.some(
      (part) =>
        part.type === "tool-call" &&
        part.approval !== undefined &&
        part.approval.approved === undefined &&
        part.approval.resolution === undefined,
    ),
  );
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

  useEffect(() => {
    if (shouldClearTransientRunError(latestRun?.status)) onSuccessfulRun();
  }, [latestRun?.status, onSuccessfulRun]);

  const status = isRunning
    ? "running"
    : hasPendingApproval
      ? "Awaiting approval"
      : latestRun?.status;
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
  onApprovals: (records: ResolvedApproval[]) => void,
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
        approvals?: ResolvedApproval[];
        interrupts?: AgUiInterrupt[];
        messages?: unknown[];
      };
      onApprovals(body.approvals ?? []);
      const interrupts = body.interrupts ?? [];
      const restored = restoreInterruptMetadata(
        body.messages ?? [],
        interrupts,
      );
      const converted = restoreResolvedApprovals(
        fromAgUiMessages(restored.messages),
        body.approvals ?? [],
      );
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
  onOpenArtifact,
  onOpenFileProposal,
  onOpenVirtualFile,
  onUserMessage,
  projectId,
  threadId,
}: {
  onOpenArtifact?: (artifactId: string) => void;
  onOpenFileProposal: (proposal: ProposedFileReview) => void;
  onOpenVirtualFile: (path: string) => void;
  onUserMessage?: (message: string) => void;
  projectId: string;
  threadId: string;
}) {
  const [error, setError] = useState<string | null>(null);
  const [approvalHistory, setApprovalHistory] = useState<
    Record<string, ResolvedApproval>
  >({});
  const agent = useMemo(
    () =>
      new InterruptSafeHttpAgent({
        threadId,
        url: `/api/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(threadId)}/agent`,
      }),
    [projectId, threadId],
  );
  const history = useMemo(
    () =>
      createHistoryAdapter(projectId, threadId, (records) => {
        setApprovalHistory(
          Object.fromEntries(
            records.map((record) => [record.toolCallId, record]),
          ),
        );
      }),
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
    <ProjectIdContext.Provider value={projectId}>
      <ApprovalHistoryContext.Provider value={approvalHistory}>
        <OpenArtifactContext.Provider value={onOpenArtifact ?? (() => {})}>
          <OpenFileProposalContext.Provider value={onOpenFileProposal}>
            <OpenVirtualFileContext.Provider value={onOpenVirtualFile}>
              <AssistantRuntimeProvider runtime={runtime}>
                <ThreadPrimitive.Root className={styles.thread}>
                  <ThreadPrimitive.Viewport className={styles.viewport}>
                    <ThreadPrimitive.Empty>
                      <div className={styles.empty}>
                        <h1>What are we working on?</h1>
                        <p>
                          This Thread keeps its own conversation state within
                          the Project.
                        </p>
                      </div>
                    </ThreadPrimitive.Empty>
                    <ConversationMessages />
                    <RunStatus
                      onSuccessfulRun={() => setError(null)}
                      runsUrl={runsUrl}
                    />
                    {error ? <p className={styles.runError}>{error}</p> : null}
                    <ThreadPrimitive.ViewportFooter className={styles.footer}>
                      <ComposerArea onSubmit={captureUserMessage} />
                    </ThreadPrimitive.ViewportFooter>
                  </ThreadPrimitive.Viewport>
                </ThreadPrimitive.Root>
              </AssistantRuntimeProvider>
            </OpenVirtualFileContext.Provider>
          </OpenFileProposalContext.Provider>
        </OpenArtifactContext.Provider>
      </ApprovalHistoryContext.Provider>
    </ProjectIdContext.Provider>
  );
}
