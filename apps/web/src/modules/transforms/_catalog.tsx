"use client";

import { FormEvent, useEffect, useState } from "react";

import { Button, Field } from "@/shared/ui";

import styles from "./transform.module.css";

interface Definition {
  id: string;
  name: string;
  source: string;
  inputSelectors: Record<string, string>;
  outputSchema: Record<string, unknown>;
  runtime: string | null;
  packageHash: string | null;
  revision: number;
}

interface Run {
  id: string;
  definitionId: string;
  status: string;
  definitionSnapshot: {
    name: string;
    source: string;
    input_selectors: Record<string, string>;
    revision: number;
    selection?: {
      sourceKind?: string;
      datasetId?: string;
      datasetVersion?: number;
      datasetPath?: string;
      recordIds?: string[];
      sourceRunId?: string;
      batchRunId?: string;
      outputPath?: string;
      rule: Record<string, unknown>;
      selectedCount: number;
    };
  };
  inputs: Record<string, unknown>;
  parameters: Record<string, unknown>;
  inputHash: string;
  sourceHash: string;
  packageHash: string | null;
  runtime: string | null;
  output: unknown;
  outputManifest: { bytes?: number; sha256?: string };
  error: string | null;
  initiation: {
    kind: string;
    approval: string;
    threadId: string | null;
    agentRunId: string | null;
  };
  limits: {
    timeoutMs?: number;
    maxInputBytes?: number;
    maxOutputBytes?: number;
  };
  createdAt: string;
}

interface RunPage {
  items: Run[];
  nextOffset: number | null;
}

interface Preview {
  output: unknown;
  runtime: string;
  sourceHash: string;
}

interface DatasetOption {
  id: string;
  name: string;
  version: number;
}

interface BatchRunOption {
  id: string;
  definitionId: string;
  status: string;
  succeededCount: number;
  failedCount: number;
}

interface SelectionRuleRequest {
  expectedDefinitionRevision: number;
  filterPath: string | null;
  equals: string | number | boolean | null;
  sortPath: string | null;
  descending: boolean;
  limit: number | null;
  parameters: Record<string, unknown>;
}

interface DatasetSelectionRequest extends SelectionRuleRequest {
  datasetId: string;
  expectedVersion: number;
}

interface OutputSelectionRequest extends SelectionRuleRequest {
  sourceRunId: string;
  outputPath: string;
}

type SelectionRequest = DatasetSelectionRequest | OutputSelectionRequest;

interface SelectionPlan {
  selection: {
    sourceKind?: string;
    datasetId?: string;
    datasetVersion?: number;
    sourceRunId?: string;
    batchRunId?: string;
    outputPath?: string;
    recordIds?: string[];
    records?: Array<{ id: string; value: Record<string, unknown> }>;
    values?: Array<Record<string, unknown>>;
    selectedRecords?: Array<{ datasetRecordId: string; input: Record<string, unknown>; value: unknown }>;
    rule: Record<string, unknown>;
  };
  selectedCount: number;
  invocationCount: number;
  outputLocation: string;
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

function jsonObject(raw: string, label: string): Record<string, unknown> {
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be a JSON object.`);
  }
  return value as Record<string, unknown>;
}

function shortId(value: string): string {
  return value.slice(0, 8);
}

export function TransformCatalog({ projectId }: { projectId: string }) {
  const root = `/api/projects/${encodeURIComponent(projectId)}/transforms`;
  const [definitions, setDefinitions] = useState<Definition[] | null>(null);
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [selectedDefinitionId, setSelectedDefinitionId] = useState<
    string | null
  >(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [recordJson, setRecordJson] = useState('{"load": 3}');
  const [parametersJson, setParametersJson] = useState("{}");
  const [inputMode, setInputMode] = useState<"record" | "dataset" | "output" | "resultSet">(
    "record",
  );
  const [datasetOptions, setDatasetOptions] = useState<DatasetOption[]>([]);
  const [batchRunOptions, setBatchRunOptions] = useState<BatchRunOption[]>([]);
  const [selectionDatasetId, setSelectionDatasetId] = useState("");
  const [selectionRunId, setSelectionRunId] = useState("");
  const [selectionBatchRunId, setSelectionBatchRunId] = useState("");
  const [outputPath, setOutputPath] = useState("");
  const [filterPath, setFilterPath] = useState("");
  const [filterEquals, setFilterEquals] = useState("");
  const [sortPath, setSortPath] = useState("");
  const [descending, setDescending] = useState(false);
  const [selectionLimit, setSelectionLimit] = useState("");
  const [selectionPlan, setSelectionPlan] = useState<{
    plan: SelectionPlan;
    request: SelectionRequest;
    endpoint: string;
  } | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [saveName, setSaveName] = useState("Transform output");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selectedDefinition = definitions?.find(
    (item) => item.id === selectedDefinitionId,
  );
  const selectedRun = runs?.find((item) => item.id === selectedRunId);

  async function refreshDatasets() {
    const response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/datasets`,
      { cache: "no-store" },
    );
    if (!response.ok) throw new Error("Datasets could not be loaded.");
    setDatasetOptions((await response.json()) as DatasetOption[]);
  }

  async function refreshBatchRuns() {
    const response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/batch-runs?limit=100&include_archived=true`,
      { cache: "no-store" },
    );
    if (!response.ok) throw new Error("Batch Runs could not be loaded.");
    const page = (await response.json()) as { items: BatchRunOption[] };
    setBatchRunOptions(page.items);
  }

  useEffect(() => {
    let active = true;
    void fetch(`/api/projects/${encodeURIComponent(projectId)}/datasets`, {
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Datasets could not be loaded.");
        const available = (await response.json()) as DatasetOption[];
        if (active) setDatasetOptions(available);
      })
      .catch(() => {
        if (active) setError("Datasets could not be loaded.");
      });
    return () => {
      active = false;
    };
  }, [projectId]);

  useEffect(() => {
    let active = true;
    void Promise.all([
      fetch(root, { cache: "no-store" }),
      fetch(`${root}/runs?limit=20`, { cache: "no-store" }),
    ])
      .then(async ([definitionResponse, runResponse]) => {
        if (!definitionResponse.ok || !runResponse.ok) {
          throw new Error("Transforms could not be loaded.");
        }
        const [available, page] = await Promise.all([
          definitionResponse.json() as Promise<Definition[]>,
          runResponse.json() as Promise<RunPage>,
        ]);
        if (!active) return;
        setDefinitions(available);
        setRuns(page.items);
        setNextOffset(page.nextOffset);
        setSelectedDefinitionId(available[0]?.id ?? null);
        setSelectedRunId(page.items[0]?.id ?? null);
      })
      .catch((cause: unknown) => {
        if (active)
          setError(
            cause instanceof Error
              ? cause.message
              : "Transforms could not be loaded.",
          );
      });
    return () => {
      active = false;
    };
  }, [root]);

  async function saveDefinition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy("definition");
    setError(null);
    try {
      const inputSelectors = jsonObject(
        String(form.get("inputSelectors")),
        "Input selectors",
      );
      if (
        Object.values(inputSelectors).some((value) => typeof value !== "string")
      ) {
        throw new Error("Each input selector must be a JSON Pointer string.");
      }
      const body = {
        name: String(form.get("name")),
        source: String(form.get("source")),
        inputSelectors,
        outputSchema: jsonObject(
          String(form.get("outputSchema")),
          "Output schema",
        ),
      };
      const endpoint = selectedDefinition
        ? `${root}/${encodeURIComponent(selectedDefinition.id)}`
        : root;
      const response = await fetch(endpoint, {
        method: selectedDefinition ? "PUT" : "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok)
        throw new Error(
          await responseError(response, "Definition could not be saved."),
        );
      const saved = (await response.json()) as Definition;
      setDefinitions((current) => [
        ...(current ?? []).filter((item) => item.id !== saved.id),
        saved,
      ]);
      setSelectedDefinitionId(saved.id);
      setIsEditing(false);
      setPreview(null);
      setSelectionPlan(null);
      setNotice(`${saved.name} saved as revision ${saved.revision}.`);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Definition could not be saved.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function deleteDefinition() {
    if (
      !selectedDefinition ||
      !window.confirm(
        `Delete ${selectedDefinition.name}? Retained Runs will remain available.`,
      )
    )
      return;
    setBusy("delete");
    setError(null);
    try {
      const response = await fetch(
        `${root}/${encodeURIComponent(selectedDefinition.id)}`,
        { method: "DELETE" },
      );
      if (!response.ok)
        throw new Error(
          await responseError(response, "Definition could not be deleted."),
        );
      setDefinitions(
        (current) =>
          current?.filter((item) => item.id !== selectedDefinition.id) ?? [],
      );
      setSelectedDefinitionId(null);
      setPreview(null);
      setSelectionPlan(null);
      setNotice("Definition deleted. Its Runs remain available below.");
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Definition could not be deleted.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function execute(mode: "preview" | "runs") {
    if (!selectedDefinition) return;
    setBusy(mode);
    setError(null);
    setNotice(null);
    try {
      const body = {
        record: jsonObject(recordJson, "Input record"),
        parameters: jsonObject(parametersJson, "Parameters"),
      };
      const response = await fetch(
        `${root}/${encodeURIComponent(selectedDefinition.id)}/${mode}`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        },
      );
      if (!response.ok)
        throw new Error(
          await responseError(response, "Transform could not be executed."),
        );
      if (mode === "preview") {
        setPreview((await response.json()) as Preview);
      } else {
        const run = (await response.json()) as Run;
        setRuns((current) => [
          run,
          ...(current ?? []).filter((item) => item.id !== run.id),
        ]);
        setSelectedRunId(run.id);
        setPreview(null);
        setNotice(`Run ${shortId(run.id)} ${run.status}.`);
      }
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Transform could not be executed.",
      );
    } finally {
      setBusy(null);
    }
  }

  function selectionRequest(): SelectionRequest {
    if (!selectedDefinition) throw new Error("Select a Transform Definition.");
    let equals: SelectionRequest["equals"] = null;
    if (filterPath.trim()) {
      if (!filterEquals.trim()) throw new Error("Enter a JSON equality value.");
      const parsed: unknown = JSON.parse(filterEquals);
      if (
        parsed !== null &&
        !["string", "number", "boolean"].includes(typeof parsed)
      )
        throw new Error("Equality value must be a JSON scalar.");
      equals = parsed as SelectionRequest["equals"];
    }
    const rule = {
      expectedDefinitionRevision: selectedDefinition.revision,
      filterPath: filterPath.trim() || null,
      equals,
      sortPath: sortPath.trim() || null,
      descending,
      limit: selectionLimit.trim() ? Number(selectionLimit) : null,
      parameters: jsonObject(parametersJson, "Parameters"),
    };
    if (inputMode === "output") {
      if (!selectionRunId) throw new Error("Select a completed Transform Run.");
      if (!outputPath.trim()) throw new Error("Enter an output JSON Pointer.");
      return {
        ...rule,
        sourceRunId: selectionRunId,
        outputPath: outputPath.trim(),
      };
    }
    if (inputMode === "resultSet") {
      if (!selectionBatchRunId) throw new Error("Select a completed Batch Run.");
      return {
        ...rule,
        sourceRunId: selectionBatchRunId,
        outputPath: outputPath.trim(),
      };
    }
    const dataset = datasetOptions.find(
      (item) => item.id === selectionDatasetId,
    );
    if (!dataset) throw new Error("Select a Dataset.");
    return {
      ...rule,
      datasetId: dataset.id,
      expectedVersion: dataset.version,
    };
  }

  async function reviewSelection() {
    if (!selectedDefinition) return;
    setBusy("selection-plan");
    setError(null);
    setSelectionPlan(null);
    try {
      const request = selectionRequest();
      const endpoint = inputMode === "output" ? "output-selection"
        : inputMode === "resultSet" ? "result-set-selection" : "selection";
      const response = await fetch(
        `${root}/${encodeURIComponent(selectedDefinition.id)}/${endpoint}-plan`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(request),
        },
      );
      if (!response.ok)
        throw new Error(
          await responseError(response, "Selection could not be reviewed."),
        );
      setSelectionPlan({
        plan: (await response.json()) as SelectionPlan,
        request,
        endpoint,
      });
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Selection could not be reviewed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function runSelection() {
    if (!selectedDefinition || !selectionPlan) return;
    setBusy("selection-run");
    setError(null);
    try {
      const response = await fetch(
        `${root}/${encodeURIComponent(selectedDefinition.id)}/${selectionPlan.endpoint}-runs`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(selectionPlan.request),
        },
      );
      if (!response.ok)
        throw new Error(
          await responseError(response, "Selected Run could not be started."),
        );
      let run = (await response.json()) as Run;
      if (selectionPlan.endpoint === "result-set-selection") {
        const detail = await fetch(
          `${root}/runs/${encodeURIComponent(run.id)}`,
          { cache: "no-store" },
        );
        if (!detail.ok) throw new Error("Run started, but its details could not be loaded.");
        run = (await detail.json()) as Run;
      }
      setRuns((current) => [
        run,
        ...(current ?? []).filter((item) => item.id !== run.id),
      ]);
      setSelectedRunId(run.id);
      setSelectionPlan(null);
      setNotice(`Run ${shortId(run.id)} ${run.status}.`);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Selected Run could not be started.",
      );
      setSelectionPlan(null);
    } finally {
      setBusy(null);
    }
  }

  async function loadMoreRuns() {
    if (nextOffset === null) return;
    setBusy("more");
    setError(null);
    try {
      const response = await fetch(
        `${root}/runs?limit=20&offset=${nextOffset}`,
        { cache: "no-store" },
      );
      if (!response.ok)
        throw new Error(
          await responseError(response, "Runs could not be loaded."),
        );
      const page = (await response.json()) as RunPage;
      setRuns((current) => [...(current ?? []), ...page.items]);
      setNextOffset(page.nextOffset);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Runs could not be loaded.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function saveDataset() {
    if (!selectedRun) return;
    setBusy("save-dataset");
    setError(null);
    try {
      const response = await fetch(
        `${root}/runs/${encodeURIComponent(selectedRun.id)}/save-dataset`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ name: saveName }),
        },
      );
      if (!response.ok)
        throw new Error(
          await responseError(response, "Output could not be saved."),
        );
      const result = (await response.json()) as {
        id: string;
        recordCount: number;
      };
      setNotice(
        `Saved ${result.recordCount} record${result.recordCount === 1 ? "" : "s"} as Dataset ${shortId(result.id)}.`,
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Output could not be saved.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function saveArtifact() {
    if (!selectedRun) return;
    setBusy("save-artifact");
    setError(null);
    try {
      const response = await fetch(
        `${root}/runs/${encodeURIComponent(selectedRun.id)}/save-artifact`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ title: saveName }),
        },
      );
      if (!response.ok)
        throw new Error(
          await responseError(response, "Artifact could not be saved."),
        );
      const document = (await response.json()) as { artifact: { id: string } };
      setNotice(
        `Saved Artifact ${shortId(document.artifact.id)} in Project Work.`,
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Artifact could not be saved.",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <section aria-label="Transforms" className={styles.catalog}>
      <header className={styles.heading}>
        <div>
          <h1>Transforms</h1>
          <p>
            Shape Project data with a reviewed Python definition. Preview before
            creating a retained Run.
          </p>
        </div>
        <Button
          onClick={() => {
            setSelectedDefinitionId(null);
            setIsEditing(true);
            setPreview(null);
            setSelectionPlan(null);
          }}
          variant="primary"
        >
          New Transform
        </Button>
      </header>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className={styles.notice} role="status">
          {notice}
        </p>
      ) : null}
      {definitions === null || runs === null ? (
        <p role="status">Loading Transforms…</p>
      ) : null}

      <div className={styles.columns}>
        <section aria-label="Definitions" className={styles.library}>
          <h2>Definitions</h2>
          {definitions?.length === 0 ? (
            <p>No Definitions yet. Create one to start with an input record.</p>
          ) : null}
          <ul className={styles.definitionList}>
            {definitions?.map((item) => (
              <li key={item.id}>
                <button
                  aria-pressed={selectedDefinitionId === item.id}
                  className={styles.definitionButton}
                  onClick={() => {
                    setSelectedDefinitionId(item.id);
                    setIsEditing(false);
                    setPreview(null);
                    setSelectionPlan(null);
                  }}
                  type="button"
                >
                  <strong>{item.name}</strong>
                  <span>
                    Revision {item.revision} · {shortId(item.id)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <div className={styles.work}>
          {isEditing ? (
            <form
              className={styles.form}
              key={selectedDefinitionId ?? "new"}
              onSubmit={(event) => void saveDefinition(event)}
            >
              <div className={styles.sectionHeading}>
                <h2>
                  {selectedDefinition
                    ? `Edit ${selectedDefinition.name}`
                    : "New Definition"}
                </h2>
                <Button onClick={() => setIsEditing(false)} type="button">
                  Cancel
                </Button>
              </div>
              <Field label="Name">
                <input
                  defaultValue={selectedDefinition?.name}
                  name="name"
                  required
                />
              </Field>
              <Field label="Python source">
                <textarea
                  defaultValue={
                    selectedDefinition?.source ??
                    "def transform(inputs, parameters):\n    return {'value': inputs['load'] * parameters.get('factor', 1)}\n"
                  }
                  name="source"
                  required
                  rows={9}
                  spellCheck={false}
                />
              </Field>
              <div className={styles.formGrid}>
                <Field label="Input selectors (JSON object)">
                  <textarea
                    defaultValue={JSON.stringify(
                      selectedDefinition?.inputSelectors ?? { load: "/load" },
                      null,
                      2,
                    )}
                    name="inputSelectors"
                    required
                    rows={4}
                    spellCheck={false}
                  />
                </Field>
                <Field label="Output schema (JSON Schema)">
                  <textarea
                    defaultValue={JSON.stringify(
                      selectedDefinition?.outputSchema ?? { type: "object" },
                      null,
                      2,
                    )}
                    name="outputSchema"
                    required
                    rows={4}
                    spellCheck={false}
                  />
                </Field>
              </div>
              <Button disabled={busy !== null} type="submit" variant="primary">
                {busy === "definition" ? "Saving…" : "Save Definition"}
              </Button>
            </form>
          ) : selectedDefinition ? (
            <section
              aria-label="Selected Definition"
              className={styles.definitionDetail}
            >
              <div className={styles.sectionHeading}>
                <div>
                  <h2>{selectedDefinition.name}</h2>
                  <p>
                    Revision {selectedDefinition.revision} ·{" "}
                    {selectedDefinition.runtime ?? "Runner unavailable"}
                  </p>
                </div>
                <div className={styles.actions}>
                  <Button onClick={() => setIsEditing(true)}>Edit</Button>
                  <Button
                    onClick={() => void deleteDefinition()}
                    variant="danger"
                  >
                    Delete
                  </Button>
                </div>
              </div>
              <details>
                <summary>View source and contract</summary>
                <pre>{selectedDefinition.source}</pre>
                <pre>
                  {JSON.stringify(
                    {
                      inputSelectors: selectedDefinition.inputSelectors,
                      outputSchema: selectedDefinition.outputSchema,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
              <Field label="Input source">
                <select
                  onChange={(event) => {
                    setInputMode(
                      event.target.value as "record" | "dataset" | "output" | "resultSet",
                    );
                    setSelectionPlan(null);
                    if (event.target.value === "resultSet") {
                      void refreshBatchRuns().catch(() => setError("Batch Runs could not be loaded."));
                    }
                  }}
                  value={inputMode}
                >
                  <option value="record">Single input record</option>
                  <option value="dataset">Selected Dataset Records</option>
                  <option value="output">Selected Transform Run output</option>
                  <option value="resultSet">Selected Batch Result Set values</option>
                </select>
              </Field>
              {inputMode === "record" ? (
                <>
                  <div className={styles.formGrid}>
                    <Field label="Input record (JSON object)">
                      <textarea
                        onChange={(event) => setRecordJson(event.target.value)}
                        rows={5}
                        spellCheck={false}
                        value={recordJson}
                      />
                    </Field>
                    <Field label="Parameters (JSON object)">
                      <textarea
                        onChange={(event) =>
                          setParametersJson(event.target.value)
                        }
                        rows={5}
                        spellCheck={false}
                        value={parametersJson}
                      />
                    </Field>
                  </div>
                  <div className={styles.actions}>
                    <Button
                      disabled={busy !== null}
                      onClick={() => void execute("preview")}
                    >
                      {busy === "preview" ? "Previewing…" : "Preview output"}
                    </Button>
                    <Button
                      disabled={busy !== null}
                      onClick={() => void execute("runs")}
                      variant="primary"
                    >
                      {busy === "runs" ? "Running…" : "Start durable Run"}
                    </Button>
                  </div>
                </>
              ) : (
                <section aria-label="Value selection" className={styles.form}>
                  <p>
                    Select values in source order, or add a filter, sort, and
                    limit. The reviewed values become one Transform input.
                    {inputMode === "output"
                      ? " The output path must select a list of JSON objects."
                      : null}
                  </p>
                  {inputMode === "dataset" ? (
                    <div className={styles.actions}>
                      <Field label="Dataset">
                        <select
                          onChange={(event) => {
                            setSelectionDatasetId(event.target.value);
                            setSelectionPlan(null);
                          }}
                          value={selectionDatasetId}
                        >
                          <option value="">Select Dataset</option>
                          {datasetOptions.map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.name} · v{item.version}
                            </option>
                          ))}
                        </select>
                      </Field>
                      <Button
                        onClick={() =>
                          void refreshDatasets()
                            .then(() => setSelectionPlan(null))
                            .catch(() =>
                              setError("Datasets could not be loaded."),
                            )
                        }
                      >
                        Refresh Datasets
                      </Button>
                    </div>
                  ) : inputMode === "output" ? (
                    <div className={styles.formGrid}>
                      <Field label="Transform Run">
                        <select
                          onChange={(event) => {
                            setSelectionRunId(event.target.value);
                            setSelectionPlan(null);
                          }}
                          value={selectionRunId}
                        >
                          <option value="">Select completed Run</option>
                          {(runs ?? [])
                            .filter((run) => run.status === "succeeded")
                            .map((run) => (
                              <option key={run.id} value={run.id}>
                                {run.definitionSnapshot.name} ·{" "}
                                {shortId(run.id)}
                              </option>
                            ))}
                        </select>
                      </Field>
                      <Field label="Output path (JSON Pointer)">
                        <input
                          onChange={(event) => {
                            setOutputPath(event.target.value);
                            setSelectionPlan(null);
                          }}
                          placeholder="/items"
                          value={outputPath}
                        />
                      </Field>
                    </div>
                  ) : (
                    <div className={styles.formGrid}>
                      <Field label="Batch Run Result Set">
                        <select
                          onChange={(event) => {
                            setSelectionBatchRunId(event.target.value);
                            setSelectionPlan(null);
                          }}
                          value={selectionBatchRunId}
                        >
                          <option value="">Select completed Batch Run</option>
                          {batchRunOptions
                            .filter((run) => run.status === "succeeded" || run.status === "partial")
                            .map((run) => (
                              <option key={run.id} value={run.id}>
                                {shortId(run.definitionId)} · {shortId(run.id)} · {run.succeededCount} results
                              </option>
                            ))}
                        </select>
                      </Field>
                      <Field label="Value path in each result (JSON Pointer; empty uses whole output)">
                        <input
                          onChange={(event) => {
                            setOutputPath(event.target.value);
                            setSelectionPlan(null);
                          }}
                          placeholder="/value"
                          value={outputPath}
                        />
                      </Field>
                      <Button onClick={() => void refreshBatchRuns().catch(() => setError("Batch Runs could not be loaded."))}>
                        Refresh Batch Runs
                      </Button>
                    </div>
                  )}
                  <div className={styles.formGrid}>
                    <Field label="Filter path (JSON Pointer, optional)">
                      <input
                        onChange={(event) => {
                          setFilterPath(event.target.value);
                          setSelectionPlan(null);
                        }}
                        placeholder="/group"
                        value={filterPath}
                      />
                    </Field>
                    <Field label="Equals (JSON scalar)">
                      <input
                        onChange={(event) => {
                          setFilterEquals(event.target.value);
                          setSelectionPlan(null);
                        }}
                        placeholder='"A"'
                        value={filterEquals}
                      />
                    </Field>
                    <Field label="Sort path (JSON Pointer, optional)">
                      <input
                        onChange={(event) => {
                          setSortPath(event.target.value);
                          setSelectionPlan(null);
                        }}
                        placeholder="/score"
                        value={sortPath}
                      />
                    </Field>
                    <Field label="Maximum records (optional)">
                      <input
                        min={1}
                        max={100}
                        onChange={(event) => {
                          setSelectionLimit(event.target.value);
                          setSelectionPlan(null);
                        }}
                        type="number"
                        value={selectionLimit}
                      />
                    </Field>
                  </div>
                  <label>
                    <input
                      checked={descending}
                      onChange={(event) => {
                        setDescending(event.target.checked);
                        setSelectionPlan(null);
                      }}
                      type="checkbox"
                    />{" "}
                    Descending order
                  </label>
                  <Field label="Parameters (JSON object)">
                    <textarea
                      onChange={(event) => {
                        setParametersJson(event.target.value);
                        setSelectionPlan(null);
                      }}
                      rows={3}
                      spellCheck={false}
                      value={parametersJson}
                    />
                  </Field>
                  <Button
                    disabled={
                      busy !== null ||
                      (inputMode === "dataset" ? !selectionDatasetId
                        : inputMode === "output" ? !selectionRunId : !selectionBatchRunId)
                    }
                    onClick={() => void reviewSelection()}
                  >
                    {busy === "selection-plan"
                      ? "Reviewing…"
                      : "Review selection"}
                  </Button>
                  {selectionPlan ? (
                    <section
                      aria-label="Selection plan"
                      className={styles.preview}
                    >
                      <strong>
                        {selectionPlan.plan.selectedCount}{" "}
                        {inputMode === "dataset" ? "records" : "values"} ·{" "}
                        {selectionPlan.plan.invocationCount} Transform
                        invocation
                      </strong>
                      <p>
                        {selectionPlan.plan.selection.batchRunId
                          ? `Batch Result Set ${shortId(selectionPlan.plan.selection.batchRunId)}`
                          : selectionPlan.plan.selection.sourceRunId
                          ? `Transform Run ${shortId(selectionPlan.plan.selection.sourceRunId)}`
                          : `Dataset v${selectionPlan.plan.selection.datasetVersion}`}{" "}
                        → {selectionPlan.plan.outputLocation}
                      </p>
                      <details>
                        <summary>Selected source values</summary>
                        <pre>
                          {JSON.stringify(
                            selectionPlan.plan.selection.records ??
                              selectionPlan.plan.selection.values ??
                              selectionPlan.plan.selection.selectedRecords,
                            null,
                            2,
                          )}
                        </pre>
                      </details>
                      <Button
                        disabled={
                          busy !== null ||
                          selectionPlan.plan.selectedCount === 0
                        }
                        onClick={() => void runSelection()}
                        variant="primary"
                      >
                        {busy === "selection-run"
                          ? "Running…"
                          : "Start selected Run"}
                      </Button>
                    </section>
                  ) : null}
                </section>
              )}
              {preview ? (
                <section aria-label="Preview output" className={styles.preview}>
                  <strong>Preview · not saved</strong>
                  <pre>{JSON.stringify(preview.output, null, 2)}</pre>
                </section>
              ) : null}
            </section>
          ) : !isEditing && definitions?.length ? (
            <p>Select a Definition to preview or run it.</p>
          ) : null}
        </div>
      </div>

      <section aria-label="Retained Runs" className={styles.runs}>
        <div className={styles.sectionHeading}>
          <div>
            <h2>Retained Runs</h2>
            <p>
              Runs and their results remain available after a Definition changes
              or is deleted.
            </p>
          </div>
        </div>
        {runs?.length === 0 ? (
          <p>No Runs yet. Start one from a Definition above.</p>
        ) : null}
        <div className={styles.runLayout}>
          <ul className={styles.runList}>
            {runs?.map((run) => (
              <li key={run.id}>
                <button
                  aria-pressed={selectedRunId === run.id}
                  className={styles.runButton}
                  onClick={() => setSelectedRunId(run.id)}
                  type="button"
                >
                  <strong>{run.definitionSnapshot.name}</strong>
                  <span>
                    {run.status} · {new Date(run.createdAt).toLocaleString()}
                  </span>
                </button>
              </li>
            ))}
            {nextOffset !== null ? (
              <li>
                <Button
                  disabled={busy !== null}
                  onClick={() => void loadMoreRuns()}
                >
                  {busy === "more" ? "Loading…" : "Load more Runs"}
                </Button>
              </li>
            ) : null}
          </ul>
          {selectedRun ? (
            <article aria-label="Run dataflow" className={styles.inspector}>
              <div className={styles.sectionHeading}>
                <div>
                  <h3>{selectedRun.definitionSnapshot.name}</h3>
                  <p>
                    Run {shortId(selectedRun.id)} · {selectedRun.status}
                  </p>
                </div>
              </div>
              <div
                aria-label="Input to Transform to output"
                className={styles.flow}
              >
                <section>
                  <h4>Selected inputs</h4>
                  {selectedRun.definitionSnapshot.selection ? (
                    <p>
                      {selectedRun.definitionSnapshot.selection.batchRunId
                        ? `Batch Result Set ${shortId(selectedRun.definitionSnapshot.selection.batchRunId)} · ${selectedRun.definitionSnapshot.selection.selectedCount} values`
                        : selectedRun.definitionSnapshot.selection.sourceRunId
                        ? `Transform Run ${shortId(selectedRun.definitionSnapshot.selection.sourceRunId)} · ${selectedRun.definitionSnapshot.selection.selectedCount} values`
                        : `Dataset ${shortId(selectedRun.definitionSnapshot.selection.datasetId ?? "")} · v${selectedRun.definitionSnapshot.selection.datasetVersion} · ${selectedRun.definitionSnapshot.selection.selectedCount} Records`}{" "}
                      · 1 invocation
                    </p>
                  ) : null}
                  <pre>{JSON.stringify(selectedRun.inputs, null, 2)}</pre>
                  <small>Input {shortId(selectedRun.inputHash)}</small>
                </section>
                <section>
                  <h4>Transform</h4>
                  <strong>{selectedRun.definitionSnapshot.name}</strong>
                  <p>Revision {selectedRun.definitionSnapshot.revision}</p>
                  <small>Source {shortId(selectedRun.sourceHash)}</small>
                </section>
                <section>
                  <h4>Output</h4>
                  {selectedRun.status === "succeeded" ? (
                    <pre>{JSON.stringify(selectedRun.output, null, 2)}</pre>
                  ) : (
                    <p>{selectedRun.error ?? "No output"}</p>
                  )}
                  {selectedRun.outputManifest.sha256 ? (
                    <small>
                      Output {shortId(selectedRun.outputManifest.sha256)}
                    </small>
                  ) : null}
                </section>
              </div>
              {selectedRun.definitionSnapshot.selection ? (
                <details>
                  <summary>Selection rule and source values</summary>
                  <pre>
                    {JSON.stringify(
                      selectedRun.definitionSnapshot.selection,
                      null,
                      2,
                    )}
                  </pre>
                </details>
              ) : null}
              <p className={styles.provenance}>
                {selectedRun.runtime ?? "Runtime unavailable"} · package{" "}
                {selectedRun.packageHash
                  ? shortId(selectedRun.packageHash)
                  : "unknown"}
              </p>
              <p className={styles.provenance}>
                {selectedRun.initiation.kind === "agentRun"
                  ? "Approved Agent Run"
                  : selectedRun.initiation.kind === "directUser"
                    ? "Direct user action"
                    : "Historical Run"}
                {selectedRun.limits.timeoutMs
                  ? ` · ${selectedRun.limits.timeoutMs / 1000}s timeout`
                  : ""}
              </p>
              {selectedRun.status === "succeeded" ? (
                <div className={styles.saveRow}>
                  <Field label="Output name">
                    <input
                      onChange={(event) => setSaveName(event.target.value)}
                      value={saveName}
                    />
                  </Field>
                  <Button
                    disabled={busy !== null || !saveName.trim()}
                    onClick={() => void saveDataset()}
                    variant="primary"
                  >
                    {busy === "save-dataset" ? "Saving…" : "Save as Dataset"}
                  </Button>
                  <Button
                    disabled={busy !== null || !saveName.trim()}
                    onClick={() => void saveArtifact()}
                  >
                    {busy === "save-artifact" ? "Saving…" : "Save as Artifact"}
                  </Button>
                </div>
              ) : null}
            </article>
          ) : null}
        </div>
      </section>
    </section>
  );
}
