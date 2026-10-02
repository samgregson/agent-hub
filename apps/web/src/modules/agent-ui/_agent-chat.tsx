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

function TextPart({ text }: TextMessagePartProps) {
  const openVirtualFile = useContext(OpenVirtualFileContext);
  return <Markdown onOpenVirtualFile={openVirtualFile} text={text} />;
}

function ToolCall({
  args,
  argsText,
  approval,
  isError,
  result,
  respondToApproval,
  toolCallId,
  toolName,
}: ToolCallMessagePartProps) {
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
    const target = approvalTarget(args, toolName);
    if (!waitingForDecision || !target.path || !projectId) return;
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
  }, [args, argsText, projectId, toolName, waitingForDecision]);

  if (approval) {
    const label = approvalLabel(toolName);
    const target = approvalTarget(args, toolName);
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
                  respondToApproval?.({ approved: true });
                }}
                type="button"
              >
                Approve
              </button>
              <button
                disabled={submitting || !respondToApproval}
                onClick={() => {
                  setSubmitting(true);
                  respondToApproval?.({
                    approved: false,
                    reason: "Rejected by the user",
                  });
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

  if (isApprovalOnlyTool(toolName)) return null;

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

function RunStatus({
  onSuccessfulRun,
  runsUrl,
}: {
  onSuccessfulRun: () => void;
  runsUrl: string;
}) {
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

  useEffect(() => {
    if (shouldClearTransientRunError(latestRun?.status)) onSuccessfulRun();
  }, [latestRun?.status, onSuccessfulRun]);

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
      new HttpAgent({
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
                        <p className={styles.eyebrow}>Agent Hub</p>
                        <h1>What are we working on?</h1>
                        <p>
                          This Thread keeps its own conversation state within
                          the Project.
                        </p>
                      </div>
                    </ThreadPrimitive.Empty>
                    <ThreadPrimitive.Messages components={{ Message }} />
                    <RunStatus
                      onSuccessfulRun={() => setError(null)}
                      runsUrl={runsUrl}
                    />
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
          </OpenFileProposalContext.Provider>
        </OpenArtifactContext.Provider>
      </ApprovalHistoryContext.Provider>
    </ProjectIdContext.Provider>
  );
}
