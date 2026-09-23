"use client";

import { FormEvent, useEffect, useState } from "react";

import styles from "@/modules/workspace/workspace.module.css";

interface DatasetRecord {
  id: string;
}

interface Dataset {
  id: string;
  name: string;
  records: DatasetRecord[];
}

interface BatchDefinition {
  datasetAvailable: boolean;
  id: string;
  name: string;
  pluginId: string;
  toolName: string;
}

export function DatasetCatalog({
  mode,
  projectId,
}: {
  mode: "datasets" | "definitions";
  projectId: string;
}) {
  const [datasets, setDatasets] = useState<Dataset[] | null>(null);
  const [definitions, setDefinitions] = useState<BatchDefinition[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isAdding, setIsAdding] = useState(false);

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
      .catch(() => active && setError("This Project catalog is temporarily unavailable."));
    return () => {
      active = false;
    };
  }, [mode, projectId]);

  async function createDataset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const records = JSON.parse(String(form.get("records")));
      if (!Array.isArray(records)) throw new Error("Records must be an array.");
      const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/datasets`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: form.get("name"), records }),
      });
      if (!response.ok) throw new Error("Dataset could not be saved.");
      const created = (await response.json()) as Dataset;
      setDatasets((current) => [...(current ?? []), created]);
      setIsAdding(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Dataset could not be saved.");
    }
  }

  async function deleteDataset(dataset: Dataset) {
    if (!window.confirm(`Delete ${dataset.name}? This cannot be undone.`)) return;
    const response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/datasets/${encodeURIComponent(dataset.id)}`,
      { method: "DELETE" },
    );
    if (!response.ok) {
      setError("Dataset could not be deleted.");
      return;
    }
    setDatasets((current) => current?.filter((item) => item.id !== dataset.id) ?? []);
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
          body: JSON.stringify({
            argumentMappings: JSON.parse(String(form.get("argumentMappings"))),
            datasetId: form.get("datasetId"),
            name: form.get("name"),
            pluginId: form.get("pluginId"),
            toolName: form.get("toolName"),
          }),
        },
      );
      if (!response.ok) throw new Error("Batch Definition could not be saved.");
      const created = (await response.json()) as BatchDefinition;
      setDefinitions((current) => [...(current ?? []), created]);
      setIsAdding(false);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Batch Definition could not be saved.",
      );
    }
  }

  async function deleteDefinition(definition: BatchDefinition) {
    if (!window.confirm(`Delete ${definition.name}? This cannot be undone.`)) return;
    const response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/batch-definitions/${encodeURIComponent(definition.id)}`,
      { method: "DELETE" },
    );
    if (!response.ok) {
      setError("Batch Definition could not be deleted.");
      return;
    }
    setDefinitions((current) => current?.filter((item) => item.id !== definition.id) ?? []);
  }

  return (
    <section aria-label={mode === "datasets" ? "Datasets" : "Batch Definitions"} className={styles.workCatalog}>
      {error ? <p className={styles.error}>{error}</p> : null}
      {mode === "datasets" ? (
        <>
          <button className={styles.newThread} onClick={() => setIsAdding(true)} type="button">
            + New Dataset
          </button>
          {datasets?.map((dataset) => (
            <article className={styles.workItem} key={dataset.id}>
              <div className={styles.workItemOpen}>
                <span>{dataset.name}</span>
                <small>{dataset.records.length} records</small>
              </div>
              <button
                className={styles.catalogDelete}
                onClick={() => void deleteDataset(dataset)}
                type="button"
              >
                Delete
              </button>
            </article>
          ))}
          {datasets?.length === 0 ? <p>No Datasets yet.</p> : null}
          {isAdding ? (
            <form className={styles.datasetForm} onSubmit={(event) => void createDataset(event)}>
              <label>Name<input name="name" required /></label>
              <label>Records (JSON array)<textarea defaultValue="[]" name="records" required rows={6} /></label>
              <div className={styles.datasetFormActions}>
                <button onClick={() => setIsAdding(false)} type="button">Cancel</button>
                <button type="submit">Save Dataset</button>
              </div>
            </form>
          ) : null}
        </>
      ) : (
        <>
          <button className={styles.newThread} onClick={() => setIsAdding(true)} type="button">
            + New Batch Definition
          </button>
          {definitions?.map((definition) => (
            <article className={styles.workItem} key={definition.id}>
              <div className={styles.workItemOpen}>
                <span>{definition.name}</span>
                <small>{definition.pluginId}.{definition.toolName}{definition.datasetAvailable ? "" : " · Dataset unavailable"}</small>
              </div>
              <button
                className={styles.catalogDelete}
                onClick={() => void deleteDefinition(definition)}
                type="button"
              >
                Delete
              </button>
            </article>
          ))}
          {definitions?.length === 0 ? <p>No Batch Definitions yet.</p> : null}
          {isAdding ? (
            <form className={styles.datasetForm} onSubmit={(event) => void createDefinition(event)}>
              <label>Name<input name="name" required /></label>
              <label>Dataset ID<input name="datasetId" required /></label>
              <label>Plugin ID<input defaultValue="reference-calculation" name="pluginId" required /></label>
              <label>Tool name<input defaultValue="calculate_cantilever_tip_load" name="toolName" required /></label>
              <label>
                Argument mappings (JSON object)
                <textarea defaultValue={'{"length_m":"/length","tip_load_kn":"/load"}'} name="argumentMappings" required rows={4} />
              </label>
              <div className={styles.datasetFormActions}>
                <button onClick={() => setIsAdding(false)} type="button">Cancel</button>
                <button type="submit">Save Batch Definition</button>
              </div>
            </form>
          ) : null}
        </>
      )}
    </section>
  );
}
