"use client";

import { useEffect, useState } from "react";

import styles from "./dataset.module.css";

interface DatasetRecord {
  id: string;
  position: number;
  sourceKey: string | null;
  value: Record<string, unknown>;
}

interface DatasetDocument {
  id: string;
  name: string;
  version: number;
  records: DatasetRecord[];
}

interface DraftRecord {
  id?: string;
  sourceKey: string;
  valueText: string;
}

function draftRecords(dataset: DatasetDocument): DraftRecord[] {
  return dataset.records.map((record) => ({
    id: record.id,
    sourceKey: record.sourceKey ?? "",
    valueText: JSON.stringify(record.value, null, 2),
  }));
}

export function DatasetFilePreview({
  datasetId,
  onSaved,
  projectId,
}: {
  datasetId: string;
  onSaved?: () => void;
  projectId: string;
}) {
  const [dataset, setDataset] = useState<DatasetDocument | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [records, setRecords] = useState<DraftRecord[]>([]);
  const url = `/api/projects/${encodeURIComponent(projectId)}/datasets/${encodeURIComponent(datasetId)}`;

  useEffect(() => {
    let active = true;
    fetch(url, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error();
        return (await response.json()) as DatasetDocument;
      })
      .then((loaded) => {
        if (active) setDataset(loaded);
      })
      .catch(() => {
        if (active) setError("This Dataset could not be opened.");
      });
    return () => {
      active = false;
    };
  }, [url]);

  function beginEdit() {
    if (!dataset) return;
    setName(dataset.name);
    setRecords(draftRecords(dataset));
    setError(null);
    setEditing(true);
  }

  async function save() {
    if (!dataset) return;
    let values: Array<{
      id?: string;
      sourceKey: string | null;
      value: Record<string, unknown>;
    }>;
    try {
      values = records.map((record) => {
        const value: unknown = JSON.parse(record.valueText);
        if (
          value === null ||
          Array.isArray(value) ||
          typeof value !== "object"
        ) {
          throw new Error();
        }
        return {
          ...(record.id ? { id: record.id } : {}),
          sourceKey: record.sourceKey.trim() || null,
          value: value as Record<string, unknown>,
        };
      });
    } catch {
      setError("Each Record value must be a JSON object.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const response = await fetch(url, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name,
          records: values,
          expectedVersion: dataset.version,
        }),
      });
      if (response.status === 409) {
        setError(
          "This Dataset changed since you opened it. Reopen it before saving.",
        );
        return;
      }
      if (!response.ok) throw new Error();
      setDataset((await response.json()) as DatasetDocument);
      setEditing(false);
      onSaved?.();
    } catch {
      setError("Dataset could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-label="Dataset viewer" className={styles.detail}>
      {!dataset && !error ? <p>Opening Dataset…</p> : null}
      {dataset ? (
        <>
          <header className={styles.datasetHeader}>
            <div>
              <strong>Dataset</strong>
              <h2>{dataset.name}</h2>
              <p>
                Version {dataset.version} · {dataset.records.length} Records
              </p>
            </div>
            {!editing ? (
              <button onClick={beginEdit} type="button">
                Edit Dataset
              </button>
            ) : null}
          </header>
          {editing ? (
            <form
              className={styles.form}
              onSubmit={(event) => {
                event.preventDefault();
                void save();
              }}
            >
              <label>
                Name
                <input
                  onChange={(event) => setName(event.target.value)}
                  value={name}
                />
              </label>
              {records.map((record, index) => (
                <div
                  className={styles.recordEditor}
                  key={record.id ?? `new-${index}`}
                >
                  <label>
                    Record key {index + 1}
                    <input
                      onChange={(event) =>
                        setRecords((current) =>
                          current.map((item, position) =>
                            position === index
                              ? { ...item, sourceKey: event.target.value }
                              : item,
                          ),
                        )
                      }
                      value={record.sourceKey}
                    />
                  </label>
                  <label>
                    {record.sourceKey || `Record ${index + 1}`} value (JSON)
                    <textarea
                      onChange={(event) =>
                        setRecords((current) =>
                          current.map((item, position) =>
                            position === index
                              ? { ...item, valueText: event.target.value }
                              : item,
                          ),
                        )
                      }
                      rows={4}
                      value={record.valueText}
                    />
                  </label>
                  <button
                    onClick={() =>
                      setRecords((current) =>
                        current.filter((_, position) => position !== index),
                      )
                    }
                    type="button"
                  >
                    Remove Record
                  </button>
                </div>
              ))}
              <div className={styles.formActions}>
                <button
                  onClick={() =>
                    setRecords((current) => [
                      ...current,
                      { sourceKey: "", valueText: "{}" },
                    ])
                  }
                  type="button"
                >
                  Add Record
                </button>
                <button onClick={() => setEditing(false)} type="button">
                  Cancel
                </button>
                <button disabled={saving} type="submit">
                  {saving ? "Saving…" : "Save Dataset"}
                </button>
              </div>
            </form>
          ) : (
            <div className={styles.datasetTableWrap}>
              <table className={styles.datasetTable}>
                <thead>
                  <tr>
                    <th>Order</th>
                    <th>Record</th>
                    <th>Value</th>
                  </tr>
                </thead>
                <tbody>
                  {dataset.records.map((record) => (
                    <tr key={record.id}>
                      <td>{record.position + 1}</td>
                      <td>
                        <strong>{record.sourceKey ?? record.id}</strong>
                      </td>
                      <td>
                        <code>{JSON.stringify(record.value)}</code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
