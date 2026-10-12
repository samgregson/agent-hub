"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import { Button, Field } from "@/shared/ui";

import styles from "./functions.module.css";

interface Definition {
  id: string;
  name: string;
  source: string;
  inputSelectors: Record<string, string>;
  inputSchema: Record<string, unknown>;
  outputSchema: Record<string, unknown>;
  runtime: string | null;
  revision: number;
}

interface Preview {
  output: unknown;
  runtime: string;
  sourceHash: string;
  source: string;
  revision: number;
  record: Record<string, unknown>;
  parameters: Record<string, unknown>;
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

export function FunctionCatalog({
  onSelectFunction,
  projectId,
  selectedFunctionId,
}: {
  onSelectFunction: (functionId: string | null) => void;
  projectId: string;
  selectedFunctionId: string | null;
}) {
  const root = `/api/projects/${encodeURIComponent(projectId)}/transforms`;
  const [definitions, setDefinitions] = useState<Definition[] | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [recordJson, setRecordJson] = useState('{"load": 3}');
  const [parametersJson, setParametersJson] = useState("{}");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const initialFunctionId = useRef(selectedFunctionId);

  const selectedDefinition = definitions?.find(
    (item) => item.id === selectedFunctionId,
  );

  useEffect(() => {
    let active = true;
    void fetch(root, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Functions could not be loaded.");
        return (await response.json()) as Definition[];
      })
      .then((available) => {
        if (!active) return;
        setDefinitions(available);
        if (!available.some((item) => item.id === initialFunctionId.current)) {
          onSelectFunction(available[0]?.id ?? null);
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(
            cause instanceof Error
              ? cause.message
              : "Functions could not be loaded.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, [onSelectFunction, root]);

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
        inputSchema: jsonObject(
          String(form.get("inputSchema")),
          "Input schema",
        ),
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
      if (!response.ok) {
        throw new Error(
          await responseError(response, "Function could not be saved."),
        );
      }
      const saved = (await response.json()) as Definition;
      setDefinitions((current) => [
        ...(current ?? []).filter((item) => item.id !== saved.id),
        saved,
      ]);
      onSelectFunction(saved.id);
      setIsEditing(false);
      setPreview(null);
      setNotice(`${saved.name} saved as revision ${saved.revision}.`);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Function could not be saved.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function deleteDefinition() {
    if (
      !selectedDefinition ||
      !window.confirm(`Delete ${selectedDefinition.name}?`)
    ) {
      return;
    }
    setBusy("delete");
    setError(null);
    try {
      const response = await fetch(
        `${root}/${encodeURIComponent(selectedDefinition.id)}`,
        { method: "DELETE" },
      );
      if (!response.ok) {
        throw new Error(
          await responseError(response, "Function could not be deleted."),
        );
      }
      const remaining = definitions?.filter(
        (item) => item.id !== selectedDefinition.id,
      );
      setDefinitions(remaining ?? []);
      onSelectFunction(remaining?.[0]?.id ?? null);
      setPreview(null);
      setNotice(`${selectedDefinition.name} deleted.`);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Function could not be deleted.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function previewFunction() {
    if (!selectedDefinition) return;
    setBusy("preview");
    setError(null);
    setNotice(null);
    setPreview(null);
    try {
      const record = jsonObject(recordJson, "Input record");
      const parameters = jsonObject(parametersJson, "Parameters");
      const response = await fetch(
        `${root}/${encodeURIComponent(selectedDefinition.id)}/preview`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ record, parameters }),
        },
      );
      if (!response.ok) {
        throw new Error(
          await responseError(response, "Function preview failed."),
        );
      }
      const result = (await response.json()) as Omit<
        Preview,
        "source" | "revision" | "record" | "parameters"
      >;
      setPreview({
        ...result,
        source: selectedDefinition.source,
        revision: selectedDefinition.revision,
        record,
        parameters,
      });
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Function preview failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <section aria-label="Functions" className={styles.catalog}>
      <header className={styles.heading}>
        <div>
          <h1>Functions</h1>
          <p>
            Create reusable Python functions and preview them against one input
            record. Workflows own durable execution.
          </p>
        </div>
        <Button
          onClick={() => {
            onSelectFunction(null);
            setIsEditing(true);
            setPreview(null);
          }}
          variant="primary"
        >
          New Function
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
      {definitions === null ? <p role="status">Loading Functions…</p> : null}

      <div className={styles.columns}>
        <section aria-label="Functions" className={styles.library}>
          <h2>Functions</h2>
          {definitions?.length === 0 ? (
            <p>No Functions yet. Create one to get started.</p>
          ) : null}
          <ul className={styles.definitionList}>
            {definitions?.map((item) => (
              <li key={item.id}>
                <button
                  aria-pressed={selectedFunctionId === item.id}
                  className={styles.definitionButton}
                  onClick={() => {
                    onSelectFunction(item.id);
                    setIsEditing(false);
                    setPreview(null);
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
              key={selectedFunctionId ?? "new"}
              onSubmit={(event) => void saveDefinition(event)}
            >
              <div className={styles.sectionHeading}>
                <h2>
                  {selectedDefinition
                    ? `Edit ${selectedDefinition.name}`
                    : "New Function"}
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
                <Field label="Input schema (JSON Schema)">
                  <textarea
                    defaultValue={JSON.stringify(
                      selectedDefinition?.inputSchema ?? {
                        type: "object",
                        properties: { load: { type: "number" } },
                        required: ["load"],
                        additionalProperties: false,
                      },
                      null,
                      2,
                    )}
                    name="inputSchema"
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
                {busy === "definition" ? "Saving…" : "Save Function"}
              </Button>
            </form>
          ) : selectedDefinition ? (
            <section
              aria-label="Selected Function"
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
                    disabled={busy !== null}
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
                      inputSchema: selectedDefinition.inputSchema,
                      outputSchema: selectedDefinition.outputSchema,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
              <div className={styles.formGrid}>
                <Field label="Input record (JSON object)">
                  <textarea
                    disabled={busy !== null}
                    onChange={(event) => {
                      setRecordJson(event.target.value);
                      setPreview(null);
                    }}
                    rows={5}
                    spellCheck={false}
                    value={recordJson}
                  />
                </Field>
                <Field label="Parameters (JSON object)">
                  <textarea
                    disabled={busy !== null}
                    onChange={(event) => {
                      setParametersJson(event.target.value);
                      setPreview(null);
                    }}
                    rows={5}
                    spellCheck={false}
                    value={parametersJson}
                  />
                </Field>
              </div>
              <Button
                disabled={busy !== null}
                onClick={() => void previewFunction()}
                variant="primary"
              >
                {busy === "preview" ? "Previewing…" : "Preview output"}
              </Button>
              {preview ? (
                <section aria-label="Preview output" className={styles.preview}>
                  <strong>Preview · transient, not saved</strong>
                  <p>
                    Function revision {preview.revision} · Runtime identity:{" "}
                    <code>{preview.runtime}</code>
                  </p>
                  <p>
                    Source SHA-256: <code>{preview.sourceHash}</code>
                  </p>
                  <details>
                    <summary>Captured source and inputs</summary>
                    <pre>{preview.source}</pre>
                    <pre>{JSON.stringify(preview.record, null, 2)}</pre>
                    <pre>{JSON.stringify(preview.parameters, null, 2)}</pre>
                  </details>
                  <pre>{JSON.stringify(preview.output, null, 2)}</pre>
                </section>
              ) : null}
            </section>
          ) : (
            <p>Select a Function to edit it or preview its output.</p>
          )}
        </div>
      </div>
    </section>
  );
}
