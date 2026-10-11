"use client";

import { useEffect, useRef, useState } from "react";

import { Button, Field } from "@/shared/ui";

import {
  reviewRequest,
  startRequest,
  type CallPlan,
  type CallSelection,
} from "./_contract";
import styles from "./call.module.css";

interface FunctionOption {
  id: string;
  name: string;
  revision: number;
}
interface DatasetOption {
  id: string;
  name: string;
  version: number;
}
interface PluginOption {
  id: string;
  name: string;
  version: string;
  enabled: boolean;
  tools: Array<{ name: string; readOnly: boolean }>;
}
interface ResultRecord {
  datasetRecordId: string;
  input: Record<string, unknown>;
  structuredOutput: Record<string, unknown> | null;
  error: string | null;
}
interface ResultPage {
  items: ResultRecord[];
  nextOffset: number | null;
  summary: { totalCount: number; succeededCount: number; failedCount: number };
}
interface RunState {
  id: string;
  kind: "transformRun" | "batchResultSet";
  status: string;
  inputs?: Record<string, unknown>;
  output?: unknown;
  error?: string | null;
}

async function responseError(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail || fallback;
  } catch {
    return fallback;
  }
}

const initialSelection: CallSelection = {
  targetKind: "python",
  shape: "single",
  definitionId: "",
  pluginId: "",
  toolName: "",
  datasetId: "",
  inputsJson: "{}",
  parametersJson: "{}",
};

export function OperationCallCatalog({ projectId }: { projectId: string }) {
  const root = `/api/projects/${encodeURIComponent(projectId)}`;
  const [functions, setFunctions] = useState<FunctionOption[]>([]);
  const [datasets, setDatasets] = useState<DatasetOption[]>([]);
  const [plugins, setPlugins] = useState<PluginOption[]>([]);
  const [selection, setSelection] = useState<CallSelection>(initialSelection);
  const [plan, setPlan] = useState<CallPlan | null>(null);
  const [runPlan, setRunPlan] = useState<CallPlan | null>(null);
  const [run, setRun] = useState<RunState | null>(null);
  const [results, setResults] = useState<ResultPage | null>(null);
  const [busy, setBusy] = useState<"review" | "start" | "more" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reviewGeneration = useRef(0);
  const runId = run?.id;
  const runKind = run?.kind;

  useEffect(() => {
    let active = true;
    async function loadOptions() {
      try {
        const responses = await Promise.all([
          fetch(`${root}/transforms`, { cache: "no-store" }),
          fetch(`${root}/datasets`, { cache: "no-store" }),
          fetch(`${root}/plugins`, { cache: "no-store" }),
        ]);
        if (responses.some((response) => !response.ok))
          throw new Error("Call targets could not be loaded.");
        const [loadedFunctions, loadedDatasets, loadedPlugins] =
          await Promise.all(responses.map((response) => response.json()));
        if (!active) return;
        setFunctions(loadedFunctions as FunctionOption[]);
        setDatasets(loadedDatasets as DatasetOption[]);
        setPlugins(
          (loadedPlugins as PluginOption[]).filter((plugin) => plugin.enabled),
        );
      } catch (cause) {
        if (active)
          setError(
            cause instanceof Error
              ? cause.message
              : "Call targets could not be loaded.",
          );
      }
    }
    void loadOptions();
    return () => {
      active = false;
    };
  }, [root]);

  function changeSelection(patch: Partial<CallSelection>) {
    reviewGeneration.current += 1;
    setSelection((current) => ({ ...current, ...patch }));
    setPlan(null);
    setRunPlan(null);
    setRun(null);
    setResults(null);
    setError(null);
  }

  async function review() {
    const generation = ++reviewGeneration.current;
    setBusy("review");
    setError(null);
    setPlan(null);
    setRunPlan(null);
    setRun(null);
    setResults(null);
    try {
      const request = reviewRequest(selection);
      const response = await fetch(`${root}/${request.path}/plan`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(request.body),
      });
      if (!response.ok)
        throw new Error(
          await responseError(response, "Call could not be reviewed."),
        );
      const reviewed = (await response.json()) as CallPlan;
      if (generation === reviewGeneration.current) setPlan(reviewed);
    } catch (cause) {
      if (generation === reviewGeneration.current)
        setError(
          cause instanceof Error
            ? cause.message
            : "Call could not be reviewed.",
        );
    } finally {
      setBusy(null);
    }
  }

  async function start() {
    if (!plan) return;
    setBusy("start");
    setError(null);
    try {
      const request = startRequest(plan);
      const response = await fetch(`${root}/${request.path}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(request.body),
      });
      if (!response.ok)
        throw new Error(
          await responseError(response, "Call could not be started."),
        );
      const started = (await response.json()) as { id: string; status: string };
      setRun({ ...started, kind: plan.outputKind });
      setRunPlan(plan);
      setPlan(null);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Call could not be started.",
      );
      setPlan(null);
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    if (!runId || !runKind) return;
    const inspectedRunId = runId;
    const inspectedKind = runKind;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function inspect() {
      try {
        const path =
          inspectedKind === "transformRun"
            ? `transforms/runs/${encodeURIComponent(inspectedRunId)}`
            : `batch-runs/${encodeURIComponent(inspectedRunId)}`;
        const detail = await fetch(`${root}/${path}`, { cache: "no-store" });
        if (!detail.ok) throw new Error("Call status could not be loaded.");
        const current = (await detail.json()) as RunState;
        if (!active) return;
        setRun({ ...current, kind: inspectedKind });
        if (current.status === "queued" || current.status === "running") {
          timer = setTimeout(() => void inspect(), 1000);
          return;
        }
        if (inspectedKind === "batchResultSet") {
          const response = await fetch(
            `${root}/batch-runs/${encodeURIComponent(inspectedRunId)}/results?limit=20`,
            { cache: "no-store" },
          );
          if (!response.ok)
            throw new Error("Call results could not be loaded.");
          if (active) setResults((await response.json()) as ResultPage);
        }
      } catch (cause) {
        if (active)
          setError(
            cause instanceof Error
              ? cause.message
              : "Call results are unavailable.",
          );
      }
    }
    void inspect();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [root, runId, runKind]);

  async function loadMore() {
    if (!run || !results || results.nextOffset === null) return;
    setBusy("more");
    setError(null);
    try {
      const response = await fetch(
        `${root}/batch-runs/${encodeURIComponent(run.id)}/results?limit=20&offset=${results.nextOffset}`,
        { cache: "no-store" },
      );
      if (!response.ok) throw new Error("More results could not be loaded.");
      const page = (await response.json()) as ResultPage;
      setResults({ ...page, items: [...results.items, ...page.items] });
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "More results are unavailable.",
      );
    } finally {
      setBusy(null);
    }
  }

  const selectedPlugin = plugins.find(
    (plugin) => plugin.id === selection.pluginId,
  );
  const bindings = plan?.review.bindings;
  const targetName = plan?.review.target.name;
  const datasetName = datasets.find(
    (dataset) => dataset.id === plan?.datasetId,
  )?.name;
  const runTargetName = runPlan?.review.target.name;

  return (
    <section aria-label="Calls" className={styles.catalog}>
      <header className={styles.heading}>
        <h1>Calls</h1>
        <p>
          Choose a Function or MCP tool. Review the exact inputs before starting
          a single call or a Map over a Dataset.
        </p>
      </header>
      <div className={styles.form}>
        <fieldset className={styles.fieldset} disabled={busy !== null}>
          <div className={styles.fieldGrid}>
            <Field label="Target kind">
              <select
                value={selection.targetKind}
                onChange={(event) =>
                  changeSelection({
                    targetKind: event.target
                      .value as CallSelection["targetKind"],
                  })
                }
              >
                <option value="python">Python Function</option>
                <option value="mcp">MCP tool</option>
              </select>
            </Field>
            <Field label="Call shape">
              <select
                value={selection.shape}
                onChange={(event) =>
                  changeSelection({
                    shape: event.target.value as CallSelection["shape"],
                  })
                }
              >
                <option value="single">Single call</option>
                <option value="map">Map Dataset</option>
              </select>
            </Field>
            {selection.targetKind === "python" ? (
              <Field label="Function">
                <select
                  value={selection.definitionId}
                  onChange={(event) =>
                    changeSelection({ definitionId: event.target.value })
                  }
                >
                  <option value="">Choose Function</option>
                  {functions.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} · v{item.revision}
                    </option>
                  ))}
                </select>
              </Field>
            ) : (
              <>
                <Field label="Plugin">
                  <select
                    value={selection.pluginId}
                    onChange={(event) =>
                      changeSelection({
                        pluginId: event.target.value,
                        toolName: "",
                      })
                    }
                  >
                    <option value="">Choose Plugin</option>
                    {plugins.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name} · v{item.version}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Tool">
                  <select
                    value={selection.toolName}
                    onChange={(event) =>
                      changeSelection({ toolName: event.target.value })
                    }
                  >
                    <option value="">Choose tool</option>
                    {selectedPlugin?.tools.map((item) => (
                      <option key={item.name} value={item.name}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </Field>
              </>
            )}
            {selection.shape === "map" ? (
              <Field label="Dataset">
                <select
                  value={selection.datasetId}
                  onChange={(event) =>
                    changeSelection({ datasetId: event.target.value })
                  }
                >
                  <option value="">Choose Dataset</option>
                  {datasets.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} · v{item.version}
                    </option>
                  ))}
                </select>
              </Field>
            ) : (
              <Field
                label={
                  selection.targetKind === "python"
                    ? "Inputs (JSON object)"
                    : "Arguments (JSON object)"
                }
              >
                <textarea
                  rows={4}
                  spellCheck={false}
                  value={selection.inputsJson}
                  onChange={(event) =>
                    changeSelection({ inputsJson: event.target.value })
                  }
                />
              </Field>
            )}
            {selection.targetKind === "python" ? (
              <Field label="Parameters (JSON object)">
                <textarea
                  rows={3}
                  spellCheck={false}
                  value={selection.parametersJson}
                  onChange={(event) =>
                    changeSelection({ parametersJson: event.target.value })
                  }
                />
              </Field>
            ) : null}
          </div>
        </fieldset>
        {selection.shape === "map" ? (
          <p className={styles.hint}>
            {selection.targetKind === "python"
              ? "The Function needs one named input. Each Dataset Record is passed to it once."
              : "Map is available for permitted repeat-safe MCP tools. Each Dataset Record supplies one tool call."}
          </p>
        ) : null}
        <Button disabled={busy !== null} onClick={() => void review()}>
          {busy === "review" ? "Reviewing…" : "Review Call"}
        </Button>
      </div>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      {plan ? (
        <section aria-label="Call review" className={styles.review}>
          <div className={styles.summary}>
            <strong>{targetName}</strong>
            <span>
              {plan.review.invocationCount} invocation
              {plan.review.invocationCount === 1 ? "" : "s"} ·{" "}
              {plan.review.outputKind === "transformRun"
                ? "Transform Run"
                : "Result Set"}
            </span>
            <span>
              {plan.datasetVersion
                ? `${datasetName ?? plan.datasetId} · Dataset v${plan.datasetVersion} · `
                : ""}
              {plan.definitionRevision
                ? `Function v${plan.definitionRevision}`
                : plan.pluginVersion
                  ? `Plugin v${plan.pluginVersion}`
                  : plan.pluginId}
            </span>
          </div>
          <p>
            Review this target and its inputs before starting. Agent starts
            require approval. Limit: {plan.review.maxInvocations} invocation
            {plan.review.maxInvocations === 1 ? "" : "s"}.
          </p>
          <details open>
            <summary>Bound inputs</summary>
            <pre>{JSON.stringify(bindings, null, 2)}</pre>
          </details>
          <details>
            <summary>Ports and output</summary>
            <pre>
              {JSON.stringify(
                {
                  inputPorts: plan.review.inputPorts,
                  outputPorts: plan.review.outputPorts,
                  outputKind: plan.review.outputKind,
                },
                null,
                2,
              )}
            </pre>
          </details>
          {plan.runtime ||
          plan.sourceHash ||
          plan.packageHash ||
          plan.parameters ||
          plan.inputSchema ||
          plan.outputSchema ? (
            <details>
              <summary>Execution details</summary>
              <pre>
                {JSON.stringify(
                  {
                    runtime: plan.runtime,
                    sourceHash: plan.sourceHash,
                    packageHash: plan.packageHash,
                    parameters: plan.parameters,
                    inputSchema: plan.inputSchema,
                    outputSchema: plan.outputSchema,
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
          ) : null}
          <Button
            disabled={busy !== null}
            onClick={() => void start()}
            variant="primary"
          >
            {busy === "start" ? "Starting…" : "Start Call"}
          </Button>
        </section>
      ) : null}
      {run ? (
        <section aria-label="Call result" className={styles.review}>
          <div className={styles.summary}>
            <strong>
              Run {run.id.slice(0, 8)} · {run.status}
            </strong>
            {runPlan ? (
              <span>
                {runTargetName}
                {runPlan.definitionRevision
                  ? ` · Function v${runPlan.definitionRevision}`
                  : runPlan.pluginVersion
                    ? ` · Plugin v${runPlan.pluginVersion}`
                    : ""}
                {runPlan.datasetVersion
                  ? ` · Dataset v${runPlan.datasetVersion}`
                  : ""}
              </span>
            ) : null}
            {results ? (
              <span>
                {results.summary.succeededCount} succeeded ·{" "}
                {results.summary.failedCount} failed
              </span>
            ) : null}
          </div>
          {runPlan ? (
            <details>
              <summary>Captured call</summary>
              <pre>
                {JSON.stringify(
                  {
                    ...runPlan.review,
                    parameters: runPlan.parameters,
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
          ) : null}
          {run.kind === "transformRun" ? (
            <div className={styles.values}>
              <div>
                <span>Inputs</span>
                <pre>{JSON.stringify(run.inputs, null, 2)}</pre>
              </div>
              <div>
                <span>{run.error ? "Error" : "Output"}</span>
                {run.error ? (
                  <p className={styles.error}>{run.error}</p>
                ) : (
                  <pre>{JSON.stringify(run.output, null, 2)}</pre>
                )}
              </div>
            </div>
          ) : (
            results?.items.map((item) => (
              <article className={styles.result} key={item.datasetRecordId}>
                <strong>Record {item.datasetRecordId.slice(0, 8)}</strong>
                <div className={styles.values}>
                  <div>
                    <span>Input</span>
                    <pre>{JSON.stringify(item.input, null, 2)}</pre>
                  </div>
                  <div>
                    <span>{item.error ? "Error" : "Output"}</span>
                    {item.error ? (
                      <p className={styles.error}>{item.error}</p>
                    ) : (
                      <pre>
                        {JSON.stringify(item.structuredOutput, null, 2)}
                      </pre>
                    )}
                  </div>
                </div>
              </article>
            ))
          )}
          {results?.nextOffset != null ? (
            <Button disabled={busy !== null} onClick={() => void loadMore()}>
              {busy === "more" ? "Loading…" : "Load more results"}
            </Button>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}
