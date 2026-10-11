"use client";

import { useEffect, useState } from "react";

import { Button } from "@/shared/ui";

import styles from "./transform.module.css";

interface PythonMapPlan {
  datasetId: string;
  datasetVersion: number;
  definitionId: string;
  definitionRevision: number;
  name: string;
  itemInputName: string;
  boundInputs: Array<{
    recordId: string;
    inputs: Record<string, unknown>;
  }>;
  parameters: Record<string, unknown>;
  runtime: string | null;
  sourceHash: string;
  packageHash: string | null;
  invocationCount: number;
  outputKind: "batchResultSet";
}

interface BatchRun {
  id: string;
  status: string;
  recordCount?: number;
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
  summary: {
    totalCount: number;
    succeededCount: number;
    failedCount: number;
  };
}

async function message(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail || fallback;
  } catch {
    return fallback;
  }
}

export function PythonMapReview({
  datasetId,
  definitionId,
  parametersJson,
  projectId,
}: {
  datasetId: string;
  definitionId: string;
  parametersJson: string;
  projectId: string;
}) {
  const root = `/api/projects/${encodeURIComponent(projectId)}/batch-runs`;
  const [plan, setPlan] = useState<PythonMapPlan | null>(null);
  const [run, setRun] = useState<BatchRun | null>(null);
  const [results, setResults] = useState<ResultPage | null>(null);
  const [busy, setBusy] = useState<"review" | "start" | "more" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const runId = run?.id;

  async function review() {
    setBusy("review");
    setError(null);
    setPlan(null);
    setRun(null);
    setResults(null);
    try {
      const parameters: unknown = JSON.parse(parametersJson);
      if (
        !parameters ||
        typeof parameters !== "object" ||
        Array.isArray(parameters)
      ) {
        throw new Error("Parameters must be a JSON object.");
      }
      const response = await fetch(`${root}/python-map/plan`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ definitionId, datasetId, parameters }),
      });
      if (!response.ok)
        throw new Error(await message(response, "Map could not be reviewed."));
      setPlan((await response.json()) as PythonMapPlan);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Map could not be reviewed.",
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
      const response = await fetch(`${root}/python-map`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          definitionId: plan.definitionId,
          datasetId: plan.datasetId,
          expectedDatasetVersion: plan.datasetVersion,
          expectedDefinitionRevision: plan.definitionRevision,
          parameters: plan.parameters,
        }),
      });
      if (!response.ok)
        throw new Error(await message(response, "Map could not be started."));
      setRun((await response.json()) as BatchRun);
      setPlan(null);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Map could not be started.",
      );
      setPlan(null);
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    if (!runId) return;
    const inspectedRunId = runId;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function inspect() {
      try {
        const detail = await fetch(
          `${root}/${encodeURIComponent(inspectedRunId)}`,
          {
            cache: "no-store",
          },
        );
        if (!detail.ok) throw new Error("Map status could not be loaded.");
        const current = (await detail.json()) as BatchRun;
        if (!active) return;
        setRun(current);
        if (current.status === "queued" || current.status === "running") {
          timer = setTimeout(() => void inspect(), 1000);
          return;
        }
        const result = await fetch(
          `${root}/${encodeURIComponent(current.id)}/results?limit=20`,
          { cache: "no-store" },
        );
        if (!result.ok) throw new Error("Map results could not be loaded.");
        if (active) setResults((await result.json()) as ResultPage);
      } catch (cause) {
        if (active)
          setError(
            cause instanceof Error
              ? cause.message
              : "Map results are unavailable.",
          );
      }
    }

    void inspect();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [root, runId]);

  async function loadMore() {
    if (!run || !results || results.nextOffset === null) return;
    setBusy("more");
    setError(null);
    try {
      const response = await fetch(
        `${root}/${encodeURIComponent(run.id)}/results?limit=20&offset=${results.nextOffset}`,
        { cache: "no-store" },
      );
      if (!response.ok)
        throw new Error("More Map results could not be loaded.");
      const page = (await response.json()) as ResultPage;
      setResults({ ...page, items: [...results.items, ...page.items] });
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "More Map results are unavailable.",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={styles.mapJourney}>
      <Button
        disabled={busy !== null || !datasetId}
        onClick={() => void review()}
      >
        {busy === "review" ? "Reviewing…" : "Review Map"}
      </Button>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      {plan ? (
        <section aria-label="Python Map review" className={styles.mapReview}>
          <div className={styles.mapSummary}>
            <strong>
              {plan.boundInputs.length} Records · {plan.invocationCount}{" "}
              Function calls
            </strong>
            <span>
              Dataset v{plan.datasetVersion} → {plan.name} v
              {plan.definitionRevision} → Result Set
            </span>
          </div>
          <p>
            Each Record is passed as <code>{plan.itemInputName}</code>. The
            Function runs once per Record.
          </p>
          <details>
            <summary>Bound inputs</summary>
            <pre>{JSON.stringify(plan.boundInputs, null, 2)}</pre>
          </details>
          <details>
            <summary>Execution details</summary>
            <dl className={styles.mapDetails}>
              <dt>Runtime</dt>
              <dd>{plan.runtime ?? "Default"}</dd>
              <dt>Source hash</dt>
              <dd>
                <code>{plan.sourceHash}</code>
              </dd>
              <dt>Package hash</dt>
              <dd>
                <code>{plan.packageHash ?? "None"}</code>
              </dd>
              <dt>Parameters</dt>
              <dd>
                <code>{JSON.stringify(plan.parameters)}</code>
              </dd>
              <dt>Output</dt>
              <dd>Durable Result Set</dd>
            </dl>
          </details>
          <Button
            disabled={busy !== null}
            onClick={() => void start()}
            variant="primary"
          >
            {busy === "start" ? "Starting…" : "Start Map"}
          </Button>
        </section>
      ) : null}
      {run ? (
        <section aria-label="Python Map results" className={styles.mapResults}>
          <div className={styles.mapSummary}>
            <strong>
              Map {run.id.slice(0, 8)} · {run.status}
            </strong>
            <span>
              {results
                ? `${results.summary.succeededCount} succeeded · ${results.summary.failedCount} failed`
                : "Results are loading…"}
            </span>
          </div>
          {results?.items.map((item) => (
            <article className={styles.mapResult} key={item.datasetRecordId}>
              <strong>Record {item.datasetRecordId.slice(0, 8)}</strong>
              <div className={styles.mapResultValues}>
                <div>
                  <span>Input</span>
                  <pre>{JSON.stringify(item.input, null, 2)}</pre>
                </div>
                <div>
                  <span>{item.error ? "Error" : "Output"}</span>
                  {item.error ? (
                    <p className={styles.error}>{item.error}</p>
                  ) : (
                    <pre>{JSON.stringify(item.structuredOutput, null, 2)}</pre>
                  )}
                </div>
              </div>
            </article>
          ))}
          {results?.nextOffset != null ? (
            <Button disabled={busy !== null} onClick={() => void loadMore()}>
              {busy === "more" ? "Loading…" : "Load more results"}
            </Button>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
