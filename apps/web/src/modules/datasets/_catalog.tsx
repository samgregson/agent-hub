"use client";

import { FormEvent, useEffect, useState } from "react";

import { Button, Collection, CollectionItem, Field } from "@/shared/ui";

import styles from "./dataset.module.css";

interface DatasetRecord {
  id: string;
  sourceKey: string | null;
  value: Record<string, unknown>;
}

interface Dataset {
  id: string;
  name: string;
  records: DatasetRecord[];
}

interface BatchDefinition {
  datasetId: string;
  datasetAvailable: boolean;
  id: string;
  name: string;
  pluginId: string | null;
  toolName: string | null;
  transformDefinitionId: string | null;
}

interface TransformDefinitionOption {
  id: string;
  name: string;
}

interface BatchRun {
  archivedAt: string | null;
  createdAt: string;
  definitionId: string;
  definitionName?: string | null;
  id: string;
  initiatorSubject: string | null;
  initiation: { kind: string; approval: string };
  status: string;
  recordCount: number;
  succeededCount: number;
  failedCount: number;
  updatedAt: string;
  definitionSnapshot?: {
    mode?: string;
    transformDefinitionId?: string;
  };
}

interface ResultRecord {
  datasetRecordId: string;
  error: string | null;
  input: Record<string, unknown>;
  structuredOutput: Record<string, unknown> | null;
}

interface ResultPage {
  items: ResultRecord[];
  nextOffset: number | null;
  summary: {
    totalCount: number;
    succeededCount: number;
    failedCount: number;
    numericCount: number;
    numericSum: number | null;
    numericMin: number | null;
    numericMax: number | null;
    numericAverage: number | null;
  };
}

interface ResultQuery {
  filterPath: string;
  exactJson: string;
  minimum: string;
  maximum: string;
  sortPath: string;
  descending: boolean;
  aggregatePath: string;
}

const emptyResultQuery: ResultQuery = {
  filterPath: "",
  exactJson: "",
  minimum: "",
  maximum: "",
  sortPath: "",
  descending: false,
  aggregatePath: "",
};

function resultQueryParams(query: ResultQuery, offset: number) {
  const params = new URLSearchParams({ limit: "20", offset: String(offset) });
  if (query.filterPath) params.set("filter_path", query.filterPath);
  if (query.exactJson)
    params.set("equals", JSON.stringify(JSON.parse(query.exactJson)));
  if (query.minimum) params.set("minimum", query.minimum);
  if (query.maximum) params.set("maximum", query.maximum);
  if (query.sortPath) params.set("sort_path", query.sortPath);
  if (query.descending) params.set("descending", "true");
  if (query.aggregatePath) params.set("aggregate_path", query.aggregatePath);
  return params;
}

interface BatchRunPage {
  items: BatchRun[];
  nextOffset: number | null;
}

function displayTool(pluginId: string, toolName: string) {
  return `${pluginId.replaceAll("-", " ")} · ${toolName.replaceAll("_", " ")}`;
}

function runSummary(run: BatchRun) {
  return `${run.status} · ${run.recordCount} records · ${run.succeededCount} succeeded${run.failedCount ? ` · ${run.failedCount} failed` : ""}`;
}

export function DatasetCatalog({
  mode,
  projectId,
}: {
  mode: "datasets" | "definitions";
  projectId: string;
}) {
  const [datasets, setDatasets] = useState<Dataset[] | null>(null);
  const [definitions, setDefinitions] = useState<BatchDefinition[] | null>(
    null,
  );
  const [transformDefinitions, setTransformDefinitions] = useState<
    TransformDefinitionOption[]
  >([]);
  const [definitionTarget, setDefinitionTarget] = useState<
    "plugin" | "transform"
  >("plugin");
  const [error, setError] = useState<string | null>(null);
  const [isAdding, setIsAdding] = useState(false);
  const [runs, setRuns] = useState<BatchRun[] | null>(null);
  const [nextRunOffset, setNextRunOffset] = useState<number | null>(null);
  const [runDefinition, setRunDefinition] = useState("all");
  const [runOrder, setRunOrder] = useState("newest");
  const [runStatus, setRunStatus] = useState("all");
  const [selectedRun, setSelectedRun] = useState<BatchRun | null>(null);
  const [resultPage, setResultPage] = useState<
    (ResultPage & { runId: string; queryKey: string }) | null
  >(null);
  const [draftResultQuery, setDraftResultQuery] =
    useState<ResultQuery>(emptyResultQuery);
  const [resultQuery, setResultQuery] = useState<ResultQuery>(emptyResultQuery);
  const resultQueryKey = JSON.stringify(resultQuery);
  const selectedRunId = selectedRun?.id;
  const selectedRunStatus = selectedRun?.status;
  const visibleResults =
    resultPage?.runId === selectedRunId &&
    resultPage?.queryKey === resultQueryKey
      ? resultPage
      : null;
  const nameForRun = (run: BatchRun) =>
    run.definitionName ??
    definitions?.find((definition) => definition.id === run.definitionId)
      ?.name ??
    `Definition ${run.definitionId.slice(0, 8)}`;
  const [selectedDataset, setSelectedDataset] = useState<Dataset | null>(null);

  useEffect(() => {
    if (!selectedRunId) return;
    let active = true;
    void fetch(
      `/api/projects/${encodeURIComponent(projectId)}/batch-runs/${encodeURIComponent(selectedRunId)}`,
      { cache: "no-store" },
    ).then(async (response) => {
      if (response.ok && active)
        setSelectedRun((await response.json()) as BatchRun);
    });
    return () => {
      active = false;
    };
  }, [projectId, selectedRunId]);

  useEffect(() => {
    let active = true;
    const endpoint = mode === "datasets" ? "datasets" : "batch-definitions";
    void fetch(`/api/projects/${encodeURIComponent(projectId)}/${endpoint}`, {
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Catalog unavailable");
        return response.json();
      })
      .then((items: Dataset[] | BatchDefinition[]) => {
        if (!active) return;
        if (mode === "datasets") setDatasets(items as Dataset[]);
        else setDefinitions(items as BatchDefinition[]);
        setError(null);
      })
      .catch(
        () =>
          active &&
          setError("This Project catalog is temporarily unavailable."),
      );
    if (mode === "definitions") {
      void fetch(`/api/projects/${encodeURIComponent(projectId)}/transforms`, {
        cache: "no-store",
      })
        .then(async (response) => {
          if (!response.ok) throw new Error("Transforms unavailable");
          return response.json() as Promise<TransformDefinitionOption[]>;
        })
        .then((items) => active && setTransformDefinitions(items))
        .catch(
          () =>
            active && setError("Transform Definitions could not be loaded."),
        );
      void fetch(`/api/projects/${encodeURIComponent(projectId)}/datasets`, {
        cache: "no-store",
      })
        .then(async (response) => {
          if (!response.ok) throw new Error("Datasets unavailable");
          return response.json() as Promise<Dataset[]>;
        })
        .then((items) => active && setDatasets(items))
        .catch(
          () =>
            active &&
            setError("This Project catalog is temporarily unavailable."),
        );
      const query = new URLSearchParams({ limit: "10", order: runOrder });
      if (runDefinition !== "all") query.set("definition_id", runDefinition);
      if (runStatus !== "all") query.set("status", runStatus);
      void fetch(
        `/api/projects/${encodeURIComponent(projectId)}/batch-runs?${query}`,
        {
          cache: "no-store",
        },
      )
        .then(async (response) => {
          if (!response.ok) throw new Error("Batch Runs unavailable");
          return response.json() as Promise<BatchRunPage>;
        })
        .then((page) => {
          if (!active) return;
          setRuns(page.items);
          setNextRunOffset(page.nextOffset);
          setSelectedRun(page.items[0] ?? null);
        })
        .catch(
          () =>
            active &&
            setError("This Project catalog is temporarily unavailable."),
        );
    }
    return () => {
      active = false;
    };
  }, [mode, projectId, runDefinition, runOrder, runStatus]);

  useEffect(() => {
    if (!selectedRun || !["queued", "running"].includes(selectedRun.status))
      return;
    const interval = window.setInterval(() => {
      void fetch(
        `/api/projects/${encodeURIComponent(projectId)}/batch-runs/${encodeURIComponent(selectedRun.id)}`,
        { cache: "no-store" },
      )
        .then((response) =>
          response.ok ? (response.json() as Promise<BatchRun>) : null,
        )
        .then((run) => {
          if (!run) return;
          setSelectedRun(run);
          setRuns(
            (current) =>
              current?.map((item) => (item.id === run.id ? run : item)) ?? [],
          );
        });
    }, 750);
    return () => window.clearInterval(interval);
  }, [projectId, selectedRun]);

  useEffect(() => {
    if (!selectedRunId) return;
    let active = true;
    const params = resultQueryParams(resultQuery, 0);
    void fetch(
      `/api/projects/${encodeURIComponent(projectId)}/batch-runs/${encodeURIComponent(selectedRunId)}/results?${params}`,
      { cache: "no-store" },
    )
      .then(async (response) => {
        if (!response.ok) throw new Error("Result Set unavailable");
        return response.json() as Promise<ResultPage>;
      })
      .then((page) => {
        if (active)
          setResultPage({
            ...page,
            runId: selectedRunId,
            queryKey: resultQueryKey,
          });
      })
      .catch(() => {
        if (active) setError("Result Set could not be loaded.");
      });
    return () => {
      active = false;
    };
  }, [
    projectId,
    selectedRunId,
    selectedRunStatus,
    resultQuery,
    resultQueryKey,
  ]);

  async function loadMoreResults() {
    if (!selectedRun || visibleResults?.nextOffset == null) return;
    const params = resultQueryParams(resultQuery, visibleResults.nextOffset);
    const response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/batch-runs/${encodeURIComponent(selectedRun.id)}/results?${params}`,
      { cache: "no-store" },
    );
    if (!response.ok) {
      setError("Result Set could not be loaded.");
      return;
    }
    const page = (await response.json()) as ResultPage;
    setResultPage((current) =>
      current?.runId === selectedRun.id && current.queryKey === resultQueryKey
        ? {
            ...page,
            items: [...current.items, ...page.items],
            runId: selectedRun.id,
            queryKey: resultQueryKey,
          }
        : { ...page, runId: selectedRun.id, queryKey: resultQueryKey },
    );
  }

  function applyResultQuery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const exact = draftResultQuery.exactJson.trim();
      if (exact) {
        const parsed: unknown = JSON.parse(exact);
        if (
          parsed === null ||
          typeof parsed === "object" ||
          !["string", "number", "boolean"].includes(typeof parsed)
        )
          throw new Error(
            "Exact JSON value must be a string, number, or boolean.",
          );
      }
      for (const value of [
        draftResultQuery.minimum,
        draftResultQuery.maximum,
      ]) {
        if (value && !Number.isFinite(Number(value)))
          throw new Error("Minimum and maximum must be finite numbers.");
      }
      setError(null);
      setResultQuery({ ...draftResultQuery, exactJson: exact });
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Result query is invalid.",
      );
    }
  }

  async function createDataset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const records = JSON.parse(String(form.get("records")));
      if (!Array.isArray(records)) throw new Error("Records must be an array.");
      const response = await fetch(
        `/api/projects/${encodeURIComponent(projectId)}/datasets`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ name: form.get("name"), records }),
        },
      );
      if (!response.ok)
        throw new Error(
          await responseMessage(response, "Dataset could not be saved."),
        );
      const created = (await response.json()) as Dataset;
      setDatasets((current) => [...(current ?? []), created]);
      setIsAdding(false);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Dataset could not be saved.",
      );
    }
  }

  async function deleteDataset(dataset: Dataset) {
    if (!window.confirm(`Delete ${dataset.name}? This cannot be undone.`))
      return;
    const response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/datasets/${encodeURIComponent(dataset.id)}`,
      { method: "DELETE" },
    );
    if (!response.ok) {
      setError("Dataset could not be deleted.");
      return;
    }
    setDatasets(
      (current) => current?.filter((item) => item.id !== dataset.id) ?? [],
    );
  }

  async function createDefinition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch(
        `/api/projects/${encodeURIComponent(projectId)}/batch-definitions`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(
            definitionTarget === "transform"
              ? {
                  datasetId: form.get("datasetId"),
                  name: form.get("name"),
                  transformDefinitionId: form.get("transformDefinitionId"),
                }
              : {
                  argumentMappings: JSON.parse(
                    String(form.get("argumentMappings")),
                  ),
                  datasetId: form.get("datasetId"),
                  name: form.get("name"),
                  pluginId: form.get("pluginId"),
                  toolName: form.get("toolName"),
                },
          ),
        },
      );
      if (!response.ok)
        throw new Error(
          await responseMessage(
            response,
            "Batch Definition could not be saved.",
          ),
        );
      const created = (await response.json()) as BatchDefinition;
      setDefinitions((current) => [...(current ?? []), created]);
      setIsAdding(false);
      requestAnimationFrame(() => {
        document.getElementById(`batch-definition-${created.id}`)?.focus();
      });
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Batch Definition could not be saved.",
      );
    }
  }

  async function deleteDefinition(definition: BatchDefinition) {
    if (
      !window.confirm(
        `Delete ${definition.name}? Its saved Batch Runs remain available as immutable history.`,
      )
    )
      return;
    const response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/batch-definitions/${encodeURIComponent(definition.id)}`,
      { method: "DELETE" },
    );
    if (!response.ok) {
      setError("Batch Definition could not be deleted.");
      return;
    }
    setDefinitions(
      (current) => current?.filter((item) => item.id !== definition.id) ?? [],
    );
  }

  async function archiveRun(run: BatchRun) {
    if (
      !window.confirm(
        "Archive this completed Batch Run? Its results and provenance will be retained.",
      )
    )
      return;
    const response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/batch-runs/${encodeURIComponent(run.id)}`,
      { method: "POST" },
    );
    if (!response.ok) {
      setError(
        await responseMessage(response, "Batch Run could not be archived."),
      );
      return;
    }
    setRuns((current) => current?.filter((item) => item.id !== run.id) ?? []);
    if (selectedRun?.id === run.id) setSelectedRun(null);
  }

  async function startOne(definitionId: string, recordId: string) {
    const response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/batch-runs`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          definitionId,
          idempotencyKey: crypto.randomUUID(),
          recordId,
        }),
      },
    );
    if (!response.ok) {
      setError(
        await responseMessage(response, "Batch Run could not be started."),
      );
      return;
    }
    const run = (await response.json()) as BatchRun;
    setRuns((current) => [
      run,
      ...(current ?? []).filter((item) => item.id !== run.id),
    ]);
    setSelectedRun(run);
  }

  async function startAll(definitionId: string) {
    const response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/batch-runs/all`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          definitionId,
          idempotencyKey: crypto.randomUUID(),
        }),
      },
    );
    if (!response.ok) {
      setError(
        await responseMessage(response, "Batch Run could not be started."),
      );
      return;
    }
    const run = (await response.json()) as BatchRun;
    setRuns((current) => [
      run,
      ...(current ?? []).filter((item) => item.id !== run.id),
    ]);
    setSelectedRun(run);
  }

  async function loadMoreRuns() {
    if (nextRunOffset === null) return;
    const query = new URLSearchParams({
      limit: "10",
      offset: String(nextRunOffset),
      order: runOrder,
    });
    if (runDefinition !== "all") query.set("definition_id", runDefinition);
    if (runStatus !== "all") query.set("status", runStatus);
    const response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/batch-runs?${query}`,
      { cache: "no-store" },
    );
    if (!response.ok) {
      setError(
        await responseMessage(response, "Batch Runs could not be loaded."),
      );
      return;
    }
    const page = (await response.json()) as BatchRunPage;
    setRuns((current) => [...(current ?? []), ...page.items]);
    setNextRunOffset(page.nextOffset);
  }

  return (
    <section
      aria-label={mode === "datasets" ? "Datasets" : "Batch Definitions"}
    >
      {error ? <p className={styles.error}>{error}</p> : null}
      {mode === "datasets" ? (
        <>
          <Button onClick={() => setIsAdding(true)} variant="primary">
            + New Dataset
          </Button>
          <Collection>
            {datasets?.map((dataset) => (
              <CollectionItem
                actions={
                  <>
                    <Button onClick={() => setSelectedDataset(dataset)}>
                      View records
                    </Button>
                    <Button
                      onClick={() => void deleteDataset(dataset)}
                      variant="danger"
                    >
                      Delete
                    </Button>
                  </>
                }
                details={`ID: ${dataset.id} · ${dataset.records.length} records · ${dataset.records.map((record) => record.id).join(", ")}`}
                key={dataset.id}
                title={dataset.name}
              />
            ))}
          </Collection>
          {selectedDataset ? (
            <section
              aria-label={`${selectedDataset.name} records`}
              className={styles.detail}
            >
              <h2>{selectedDataset.name}</h2>
              <p>{selectedDataset.records.length} records</p>
              {selectedDataset.records.map((record) => (
                <article className={styles.record} key={record.id}>
                  <strong>{record.sourceKey ?? "Record"}</strong>
                  <pre>{JSON.stringify(record.value, null, 2)}</pre>
                </article>
              ))}
            </section>
          ) : null}
          {datasets?.length === 0 ? <p>No Datasets yet.</p> : null}
          {isAdding ? (
            <form
              className={styles.form}
              onSubmit={(event) => void createDataset(event)}
            >
              <Field label="Name">
                <input name="name" required />
              </Field>
              <Field label="Records (JSON array)">
                <textarea defaultValue="[]" name="records" required rows={6} />
              </Field>
              <div className={styles.formActions}>
                <Button onClick={() => setIsAdding(false)} type="button">
                  Cancel
                </Button>
                <Button type="submit" variant="primary">
                  Save Dataset
                </Button>
              </div>
            </form>
          ) : null}
        </>
      ) : (
        <>
          <Button onClick={() => setIsAdding(true)} variant="primary">
            + New Batch Definition
          </Button>
          {isAdding ? (
            <form
              className={styles.form}
              onSubmit={(event) => void createDefinition(event)}
            >
              <Field label="Name">
                <input name="name" required />
              </Field>
              <Field label="Dataset">
                <select name="datasetId" required>
                  <option value="">Choose a Dataset…</option>
                  {datasets?.map((dataset) => (
                    <option key={dataset.id} value={dataset.id}>
                      {dataset.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Execution target">
                <select
                  onChange={(event) =>
                    setDefinitionTarget(
                      event.target.value as "plugin" | "transform",
                    )
                  }
                  value={definitionTarget}
                >
                  <option value="plugin">MCP tool</option>
                  <option value="transform">Transform Definition</option>
                </select>
              </Field>
              {definitionTarget === "transform" ? (
                <Field label="Transform Definition">
                  <select name="transformDefinitionId" required>
                    <option value="">Choose a Transform…</option>
                    {transformDefinitions.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </Field>
              ) : (
                <>
                  <Field label="Plugin ID">
                    <input
                      defaultValue="reference-calculation"
                      name="pluginId"
                      required
                    />
                  </Field>
                  <Field label="Tool name">
                    <input
                      defaultValue="calculate_cantilever_tip_load"
                      name="toolName"
                      required
                    />
                  </Field>
                  <Field label="Argument mappings (JSON object)">
                    <textarea
                      defaultValue={
                        '{"length_m":"/length","tip_load_kn":"/load"}'
                      }
                      name="argumentMappings"
                      required
                      rows={4}
                    />
                  </Field>
                </>
              )}
              <div className={styles.formActions}>
                <Button onClick={() => setIsAdding(false)} type="button">
                  Cancel
                </Button>
                <Button type="submit" variant="primary">
                  Save Batch Definition
                </Button>
              </div>
            </form>
          ) : null}
          <Collection>
            {definitions?.map((definition) => (
              <CollectionItem
                onOpen={() => {
                  setRunDefinition(definition.id);
                }}
                openLabel={`Inspect Batch Definition ${definition.name}`}
                actions={
                  <>
                    <Button
                      onClick={() => void startAll(definition.id)}
                      variant="primary"
                    >
                      Run all records
                    </Button>
                    <Button
                      onClick={() => void deleteDefinition(definition)}
                      variant="danger"
                    >
                      Delete
                    </Button>
                    <select
                      aria-label={`${definition.name} Dataset Record`}
                      className={styles.recordSelector}
                      defaultValue=""
                      onChange={(event) => {
                        if (event.target.value)
                          void startOne(definition.id, event.target.value);
                      }}
                    >
                      <option value="">Run one Dataset Record…</option>
                      {datasets
                        ?.find((dataset) => dataset.id === definition.datasetId)
                        ?.records.map((record) => (
                          <option key={record.id} value={record.id}>
                            {record.sourceKey ?? "Record"} · {record.id}
                          </option>
                        ))}
                    </select>
                  </>
                }
                details={`${
                  definition.transformDefinitionId
                    ? `Transform · ${transformDefinitions.find((item) => item.id === definition.transformDefinitionId)?.name ?? definition.transformDefinitionId.slice(0, 8)}`
                    : displayTool(
                        definition.pluginId ?? "",
                        definition.toolName ?? "",
                      )
                }${definition.datasetAvailable ? "" : " · Dataset unavailable"}`}
                id={`batch-definition-${definition.id}`}
                key={definition.id}
                title={definition.name}
              />
            ))}
          </Collection>
          {definitions?.length === 0 ? <p>No Batch Definitions yet.</p> : null}
          {runs ? (
            <section
              aria-label="Recent Batch Runs"
              className={styles.runSection}
              id="batch-runs"
            >
              <h2>
                {runDefinition === "all"
                  ? "Recent Batch Runs"
                  : `Runs for ${definitions?.find((definition) => definition.id === runDefinition)?.name ?? "Batch Definition"}`}
              </h2>
              <div className={styles.runFilters}>
                <Field label="Batch Definition">
                  <select
                    aria-label="Batch Run definition"
                    onChange={(event) => setRunDefinition(event.target.value)}
                    value={runDefinition}
                  >
                    <option value="all">All Batch Definitions</option>
                    {definitions?.map((definition) => (
                      <option key={definition.id} value={definition.id}>
                        {definition.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Status">
                  <select
                    aria-label="Batch Run status"
                    onChange={(event) => setRunStatus(event.target.value)}
                    value={runStatus}
                  >
                    <option value="all">All statuses</option>
                    <option value="succeeded">Succeeded</option>
                    <option value="partial">Partial</option>
                    <option value="failed">Failed</option>
                  </select>
                </Field>
                <Field label="Order">
                  <select
                    aria-label="Batch Run order"
                    onChange={(event) => setRunOrder(event.target.value)}
                    value={runOrder}
                  >
                    <option value="newest">Newest first</option>
                    <option value="oldest">Oldest first</option>
                  </select>
                </Field>
              </div>
              <Collection>
                {runs.map((run) => (
                  <CollectionItem
                    actions={
                      <Button onClick={() => void archiveRun(run)}>
                        Archive run
                      </Button>
                    }
                    details={`${nameForRun(run)} · ${runSummary(run)}`}
                    key={run.id}
                    onOpen={() => setSelectedRun(run)}
                    openLabel={`View Batch Run ${run.id}`}
                    title={`Run ${run.id.slice(0, 8)}`}
                  />
                ))}
              </Collection>
              {runs.length === 0 ? (
                <p>No Batch Runs match these filters.</p>
              ) : null}
              {nextRunOffset !== null ? (
                <Button onClick={() => void loadMoreRuns()}>
                  Load more runs
                </Button>
              ) : null}
            </section>
          ) : null}
          {selectedRun ? (
            <section aria-label="Batch Run results" className={styles.detail}>
              <h2>Batch Run results</h2>
              <p>
                {selectedRun.definitionSnapshot?.mode === "perRecord"
                  ? "From Transform Definition: "
                  : "From Batch Definition: "}
                {nameForRun(selectedRun)}
              </p>
              <p>{runSummary(selectedRun)}</p>
              <p>
                Result filters, ordering, and summaries only change this view;
                the completed Run and Result Set stay unchanged.
              </p>
              <p>
                {selectedRun.initiation.kind === "agentRun"
                  ? "Started by an approved agent action"
                  : selectedRun.initiation.kind === "directUser"
                    ? "Started directly by a user"
                    : "Initiator context unavailable"}
              </p>
              <form
                aria-label="Result Set query"
                className={styles.resultQuery}
                onSubmit={applyResultQuery}
              >
                <Field label="Filter field (JSON Pointer)">
                  <input
                    onChange={(event) =>
                      setDraftResultQuery((query) => ({
                        ...query,
                        filterPath: event.target.value,
                      }))
                    }
                    placeholder="/structuredOutput/score"
                    value={draftResultQuery.filterPath}
                  />
                </Field>
                <Field label="Exact JSON value">
                  <input
                    onChange={(event) =>
                      setDraftResultQuery((query) => ({
                        ...query,
                        exactJson: event.target.value,
                      }))
                    }
                    placeholder='0.8 or "passed"'
                    value={draftResultQuery.exactJson}
                  />
                </Field>
                <Field label="Minimum number">
                  <input
                    inputMode="decimal"
                    onChange={(event) =>
                      setDraftResultQuery((query) => ({
                        ...query,
                        minimum: event.target.value,
                      }))
                    }
                    value={draftResultQuery.minimum}
                  />
                </Field>
                <Field label="Maximum number">
                  <input
                    inputMode="decimal"
                    onChange={(event) =>
                      setDraftResultQuery((query) => ({
                        ...query,
                        maximum: event.target.value,
                      }))
                    }
                    value={draftResultQuery.maximum}
                  />
                </Field>
                <Field label="Sort by field (JSON Pointer)">
                  <input
                    onChange={(event) =>
                      setDraftResultQuery((query) => ({
                        ...query,
                        sortPath: event.target.value,
                      }))
                    }
                    value={draftResultQuery.sortPath}
                  />
                </Field>
                <label className={styles.resultDescending}>
                  <input
                    checked={draftResultQuery.descending}
                    onChange={(event) =>
                      setDraftResultQuery((query) => ({
                        ...query,
                        descending: event.target.checked,
                      }))
                    }
                    type="checkbox"
                  />
                  Highest first
                </label>
                <Field label="Aggregate numeric field (JSON Pointer)">
                  <input
                    onChange={(event) =>
                      setDraftResultQuery((query) => ({
                        ...query,
                        aggregatePath: event.target.value,
                      }))
                    }
                    placeholder="/structuredOutput/score"
                    value={draftResultQuery.aggregatePath}
                  />
                </Field>
                <div className={styles.resultQueryActions}>
                  <Button type="submit" variant="primary">
                    Apply result query
                  </Button>
                  <Button
                    onClick={() => {
                      setDraftResultQuery(emptyResultQuery);
                      setResultQuery(emptyResultQuery);
                    }}
                    type="button"
                  >
                    Clear query
                  </Button>
                </div>
              </form>
              {visibleResults ? (
                <>
                  <p aria-live="polite">
                    {visibleResults.summary.totalCount} results ·{" "}
                    {visibleResults.summary.succeededCount} succeeded ·{" "}
                    {visibleResults.summary.failedCount} failed
                  </p>
                  {resultQuery.aggregatePath ? (
                    <p aria-label="Numeric result summary">
                      {visibleResults.summary.numericCount} numeric values
                      {visibleResults.summary.numericSum !== null
                        ? ` · Sum: ${visibleResults.summary.numericSum}`
                        : ""}
                      {visibleResults.summary.numericMin !== null
                        ? ` · Min: ${visibleResults.summary.numericMin}`
                        : ""}
                      {visibleResults.summary.numericMax !== null
                        ? ` · Max: ${visibleResults.summary.numericMax}`
                        : ""}
                      {visibleResults.summary.numericAverage !== null
                        ? ` · Average: ${visibleResults.summary.numericAverage}`
                        : ""}
                    </p>
                  ) : null}
                </>
              ) : (
                <p aria-live="polite">Loading Result Set…</p>
              )}
              {visibleResults?.items.map((record) => (
                <article className={styles.record} key={record.datasetRecordId}>
                  <strong>Record {record.datasetRecordId.slice(0, 8)}</strong>
                  {record.error ? (
                    <p className={styles.error}>{record.error}</p>
                  ) : null}
                  <dl className={styles.resultValues}>
                    <div>
                      <dt>Input</dt>
                      <dd>{JSON.stringify(record.input)}</dd>
                    </div>
                    {record.structuredOutput ? (
                      <div>
                        <dt>Output</dt>
                        <dd>{JSON.stringify(record.structuredOutput)}</dd>
                      </div>
                    ) : null}
                  </dl>
                </article>
              ))}
              {visibleResults?.nextOffset != null ? (
                <Button onClick={() => void loadMoreResults()}>
                  Load more results
                </Button>
              ) : null}
            </section>
          ) : null}
        </>
      )}
    </section>
  );
}

async function responseMessage(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : fallback;
  } catch {
    return fallback;
  }
}
