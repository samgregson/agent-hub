"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import { Button, Field } from "@/shared/ui";
import { ImageOutputPreview, imageDataUrl } from "@/modules/media";

import {
  exampleFunctionInputs,
  hasUnspecifiedCollectionItemShape,
} from "./_preview-input";
import {
  SchemaInputFields,
  supportsSchemaInputs,
  validateSchemaInputs,
} from "./_schema-input";
import {
  functionPreviewFields,
  functionPreviewImage,
  functionPreviewSummary,
  functionPreviewReadableSummary,
  readableFunctionExample,
} from "./_preview-output";
import styles from "./functions.module.css";

interface Definition {
  id: string;
  name: string;
  source: string;
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
  inputs: Record<string, unknown>;
  parameters: Record<string, unknown>;
}

const PREVIEW_DEADLINE_MS = 45_000;
const PREVIEW_SLOW_MS = 5_000;

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

function schemaProperties(schema: Record<string, unknown> | undefined) {
  const properties = schema?.properties;
  if (
    !properties ||
    typeof properties !== "object" ||
    Array.isArray(properties)
  )
    return [];
  return Object.entries(properties as Record<string, unknown>).flatMap(
    ([name, value]) => {
      if (!value || typeof value !== "object" || Array.isArray(value))
        return [];
      const field = value as Record<string, unknown>;
      return [
        {
          name,
          type: Array.isArray(field.type)
            ? field.type.join(" | ")
            : String(field.type ?? "value"),
          description:
            typeof field.description === "string" ? field.description : "",
          unit:
            typeof field.unit === "string"
              ? field.unit
              : typeof field["x-unit"] === "string"
                ? field["x-unit"]
                : "",
          required:
            Array.isArray(schema?.required) && schema.required.includes(name),
          example:
            Array.isArray(field.examples) && field.examples.length > 0
              ? field.examples[0]
              : field.example,
        },
      ];
    },
  );
}

function parseInputValues(value: string): Record<string, unknown> | null {
  try {
    return jsonObject(value, "Function inputs");
  } catch {
    return null;
  }
}

function readablePreviewValue(value: unknown): string {
  if (value === undefined) return "Not returned";
  if (value === null) return "Null";
  if (typeof value === "string") return value || "Empty";
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    const examples = value
      .slice(0, 3)
      .map((item, index) => `#${index + 1}: ${readablePreviewValue(item)}`)
      .join(" · ");
    return `${value.length} item${value.length === 1 ? "" : "s"}${examples ? ` · ${examples}` : ""}${value.length > 3 ? " · …" : ""}`;
  }
  const entries = Object.entries(value as Record<string, unknown>);
  const summary = entries
    .slice(0, 4)
    .map(([key, item]) => `${key}: ${readablePreviewValue(item)}`)
    .join("; ");
  return `Object${summary ? ` · ${summary}` : ""}${entries.length > 4 ? "; …" : ""}`;
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
  const root = `/api/projects/${encodeURIComponent(projectId)}/functions`;
  const [definitions, setDefinitions] = useState<Definition[] | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [inputOverrides, setInputOverrides] = useState<Record<string, string>>(
    {},
  );
  const [parametersJson, setParametersJson] = useState("{}");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const initialFunctionId = useRef(selectedFunctionId);
  const previewRequest = useRef(0);
  const previewController = useRef<AbortController | null>(null);
  const [previewElapsed, setPreviewElapsed] = useState(0);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [inputErrors, setInputErrors] = useState<Record<string, string>>({});

  const selectedDefinition = definitions?.find(
    (item) => item.id === selectedFunctionId,
  );
  const inputsJson = selectedDefinition
    ? (inputOverrides[selectedDefinition.id] ??
      exampleFunctionInputs(selectedDefinition.inputSchema))
    : "{}";
  const previewImage = preview ? functionPreviewImage(preview.output) : null;
  const previewOutputFields =
    preview && selectedDefinition
      ? functionPreviewFields(preview.output, selectedDefinition.outputSchema)
      : [];
  const previewOtherOutputSummary = preview
    ? functionPreviewReadableSummary(
        preview.output,
        previewOutputFields.map((field) => field.name),
      )
    : null;
  const inputValues = parseInputValues(inputsJson) ?? {};

  useEffect(() => {
    if (busy !== "preview") return;
    const interval = window.setInterval(
      () => setPreviewElapsed((elapsed) => elapsed + 1),
      1000,
    );
    return () => window.clearInterval(interval);
  }, [busy]);

  useEffect(
    () => () => {
      previewRequest.current += 1;
      previewController.current?.abort();
    },
    [],
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
      const body = {
        name: String(form.get("name")),
        source: String(form.get("source")),
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
      setInputOverrides((current) => {
        const next = { ...current };
        delete next[saved.id];
        return next;
      });
      onSelectFunction(saved.id);
      setIsEditing(false);
      setPreview(null);
      setInputErrors({});
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
    previewController.current?.abort();
    const requestId = ++previewRequest.current;
    const controller = new AbortController();
    previewController.current = controller;
    const deadline = window.setTimeout(
      () => controller.abort(),
      PREVIEW_DEADLINE_MS,
    );
    setBusy("preview");
    setError(null);
    setNotice(null);
    setPreview(null);
    setPreviewFailed(false);
    setPreviewElapsed(0);
    try {
      const inputs = jsonObject(inputsJson, "Function inputs");
      if (supportsSchemaInputs(selectedDefinition.inputSchema)) {
        const invalid = validateSchemaInputs(
          selectedDefinition.inputSchema,
          inputs,
        );
        setInputErrors(invalid);
        if (Object.keys(invalid).length > 0) {
          setPreviewFailed(true);
          setError("Check the highlighted Function inputs before previewing.");
          return;
        }
      }
      const parameters = jsonObject(parametersJson, "Parameters");
      const response = await fetch(
        `${root}/${encodeURIComponent(selectedDefinition.id)}/preview`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ inputs, parameters }),
          signal: controller.signal,
        },
      );
      if (!response.ok) {
        const detail = await responseError(
          response,
          "Function preview failed.",
        );
        const message =
          {
            timeout:
              "The preview exceeded the runner time limit. Your inputs are still here; retry after reviewing the Function.",
            runner_unavailable:
              "The preview service is unavailable. Your inputs are still here; retry in a moment.",
            busy: "The preview service is busy. Your inputs are still here; retry in a moment.",
          }[detail] ?? detail;
        throw new Error(message);
      }
      const result = (await response.json()) as Omit<
        Preview,
        "source" | "revision" | "inputs" | "parameters"
      >;
      if (requestId !== previewRequest.current) return;
      setPreview({
        ...result,
        source: selectedDefinition.source,
        revision: selectedDefinition.revision,
        inputs,
        parameters,
      });
    } catch (cause) {
      if (requestId !== previewRequest.current) return;
      setPreviewFailed(true);
      setError(
        controller.signal.aborted
          ? `Preview timed out after ${PREVIEW_DEADLINE_MS / 1000} seconds. Your inputs are still here; retry when ready.`
          : cause instanceof Error && cause.name === "TypeError"
            ? "Could not reach the preview service. Check your connection and retry. Your inputs are still here."
            : cause instanceof Error
              ? cause.message
              : "Function preview failed. Your inputs are still here; retry when ready.",
      );
    } finally {
      window.clearTimeout(deadline);
      if (requestId === previewRequest.current) {
        previewController.current = null;
        setBusy(null);
      }
    }
  }

  return (
    <section aria-label="Functions" className={styles.catalog}>
      <header className={styles.heading}>
        <div>
          <h1>Functions</h1>
          <p>
            Create reusable Python functions and preview them with example
            inputs. Workflows own durable execution.
          </p>
        </div>
        <Button
          onClick={() => {
            onSelectFunction(null);
            setIsEditing(true);
            setPreview(null);
            setInputErrors({});
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
                    previewRequest.current += 1;
                    previewController.current?.abort();
                    previewController.current = null;
                    setBusy(null);
                    setPreviewFailed(false);
                    setInputErrors({});
                    onSelectFunction(item.id);
                    setError(null);
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
                <Field label="Input schema (JSON Schema)">
                  <textarea
                    defaultValue={JSON.stringify(
                      selectedDefinition?.inputSchema ?? {
                        type: "object",
                        description: "Calculate a result from one load value.",
                        properties: {
                          load: {
                            type: "number",
                            description: "The load to use in the calculation.",
                          },
                        },
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
                      selectedDefinition?.outputSchema ?? {
                        type: "object",
                        properties: {
                          value: {
                            type: "number",
                            description: "The calculated result.",
                          },
                        },
                        required: ["value"],
                      },
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
              <section
                aria-label="Function contract"
                className={styles.contractSummary}
              >
                <div>
                  <h3>Purpose</h3>
                  <p>
                    {typeof selectedDefinition.inputSchema.description ===
                      "string" &&
                    selectedDefinition.inputSchema.description.trim()
                      ? selectedDefinition.inputSchema.description
                      : "This Function has no purpose description yet. Add one in the input schema description."}
                  </p>
                </div>
                <div>
                  <h3>Inputs</h3>
                  <ul>
                    {schemaProperties(selectedDefinition.inputSchema).map(
                      (field) => (
                        <li key={field.name}>
                          <strong>{field.name}</strong> · {field.type} ·{" "}
                          {field.required ? "required" : "optional"}
                          {field.description ? ` — ${field.description}` : ""}
                          {field.example !== undefined
                            ? ` · Example: ${readableFunctionExample(field.example)}`
                            : ""}
                        </li>
                      ),
                    )}
                    {schemaProperties(selectedDefinition.inputSchema).length ===
                    0 ? (
                      <li>No named input fields are declared.</li>
                    ) : null}
                  </ul>
                </div>
                <div>
                  <h3>Outputs</h3>
                  <ul>
                    {schemaProperties(selectedDefinition.outputSchema).map(
                      (field) => (
                        <li key={field.name}>
                          <strong>{field.name}</strong> · {field.type}
                          {field.description ? ` — ${field.description}` : ""}
                          {field.example !== undefined
                            ? ` · Example: ${readableFunctionExample(field.example)}`
                            : ""}
                        </li>
                      ),
                    )}
                    {schemaProperties(selectedDefinition.outputSchema)
                      .length === 0 ? (
                      <li>
                        Output fields are described by the Function output
                        schema.
                      </li>
                    ) : null}
                  </ul>
                </div>
              </section>
              <details>
                <summary>View source and contract</summary>
                <pre>{selectedDefinition.source}</pre>
                <pre>
                  {JSON.stringify(
                    {
                      inputSchema: selectedDefinition.inputSchema,
                      outputSchema: selectedDefinition.outputSchema,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
              <div className={styles.inputEditor}>
                <h3>Example input</h3>
                {hasUnspecifiedCollectionItemShape(
                  selectedDefinition.inputSchema,
                ) ? (
                  <p role="note">
                    This example uses empty objects for collection items because
                    the contract does not describe their fields or provide an
                    example. Replace them with the record shape this Function
                    expects.
                  </p>
                ) : null}
                {supportsSchemaInputs(selectedDefinition.inputSchema) ? (
                  <SchemaInputFields
                    schema={selectedDefinition.inputSchema}
                    value={inputValues}
                    errors={inputErrors}
                    disabled={busy !== null}
                    onChange={(value) => {
                      setInputOverrides((current) => ({
                        ...current,
                        [selectedDefinition.id]: JSON.stringify(value, null, 2),
                      }));
                      setInputErrors({});
                      setPreview(null);
                      setPreviewFailed(false);
                      setError(null);
                    }}
                  />
                ) : (
                  <p>
                    This contract uses schema features the form cannot
                    represent. Enter a valid object in the raw JSON field below.
                  </p>
                )}
                <details>
                  <summary>
                    {supportsSchemaInputs(selectedDefinition.inputSchema)
                      ? "Edit raw JSON"
                      : "Raw JSON input"}
                  </summary>
                  <Field label="Function inputs (JSON object)">
                    <textarea
                      disabled={busy !== null}
                      onChange={(event) => {
                        setInputOverrides((current) => ({
                          ...current,
                          [selectedDefinition.id]: event.target.value,
                        }));
                        setInputErrors({});
                        setPreview(null);
                        setPreviewFailed(false);
                        setError(null);
                      }}
                      rows={5}
                      spellCheck={false}
                      value={inputsJson}
                    />
                  </Field>
                </details>
              </div>
              <details>
                <summary>Advanced: optional Function parameters</summary>
                <p>
                  Additional values passed separately from the example inputs.
                </p>
                <Field label="Parameters (JSON object)">
                  <textarea
                    disabled={busy !== null}
                    onChange={(event) => {
                      setParametersJson(event.target.value);
                      setPreview(null);
                      setPreviewFailed(false);
                      setError(null);
                    }}
                    rows={5}
                    spellCheck={false}
                    value={parametersJson}
                  />
                </Field>
              </details>
              <Button
                disabled={busy !== null}
                onClick={() => void previewFunction()}
                variant="primary"
              >
                {busy === "preview"
                  ? `Previewing… ${previewElapsed}s`
                  : previewFailed
                    ? "Retry preview"
                    : "Preview output"}
              </Button>
              {busy === "preview" &&
              previewElapsed >= PREVIEW_SLOW_MS / 1000 ? (
                <p role="status">
                  This preview is taking longer than usual ({previewElapsed}s).
                  It will finish or time out automatically.
                </p>
              ) : null}
              {preview ? (
                <section aria-label="Preview output" className={styles.preview}>
                  <strong>Preview · transient, not saved</strong>
                  <p>Function revision {preview.revision}</p>
                  <section
                    aria-label="Inputs used"
                    className={styles.previewValues}
                  >
                    <h3>Inputs used</h3>
                    {Object.entries(preview.inputs).length > 0 ? (
                      <dl>
                        {Object.entries(preview.inputs).map(([name, value]) => {
                          const field = schemaProperties(
                            selectedDefinition.inputSchema,
                          ).find((candidate) => candidate.name === name);
                          return (
                            <div key={name}>
                              <dt>{name}</dt>
                              <dd>
                                {field?.description ? (
                                  <span>{field.description} · </span>
                                ) : null}
                                {field?.unit ? (
                                  <span>{field.unit} · </span>
                                ) : null}
                                {readablePreviewValue(value)}
                              </dd>
                            </div>
                          );
                        })}
                      </dl>
                    ) : (
                      <p>No named inputs were supplied.</p>
                    )}
                  </section>
                  {previewImage ? (
                    <ImageOutputPreview
                      altText={previewImage.altText}
                      src={imageDataUrl(previewImage)}
                      title="Image output"
                    />
                  ) : null}
                  <section
                    aria-label="Output values"
                    className={styles.previewValues}
                  >
                    <h3>Output</h3>
                    {previewOutputFields.length > 0 ? (
                      <>
                        <dl>
                          {previewOutputFields.map((field) => (
                            <div key={field.name}>
                              <dt>{field.name}</dt>
                              <dd>
                                {field.description ? (
                                  <span>{field.description} · </span>
                                ) : null}
                                {field.unit ? (
                                  <span>{field.unit} · </span>
                                ) : null}
                                {readablePreviewValue(field.value)}
                              </dd>
                            </div>
                          ))}
                        </dl>
                        {previewOtherOutputSummary ? (
                          <p>
                            <strong>Other output values:</strong>{" "}
                            {previewOtherOutputSummary}
                          </p>
                        ) : null}
                      </>
                    ) : (
                      <p>
                        {preview.output !== null &&
                        typeof preview.output === "object"
                          ? functionPreviewReadableSummary(preview.output)
                          : readablePreviewValue(preview.output)}
                      </p>
                    )}
                  </section>
                  <details>
                    <summary>Technical details and full values</summary>
                    <p>
                      Runtime identity: <code>{preview.runtime}</code>
                    </p>
                    <p>
                      Source SHA-256: <code>{preview.sourceHash}</code>
                    </p>
                    <pre>{preview.source}</pre>
                    <h3>Complete inputs</h3>
                    <pre>{JSON.stringify(preview.inputs, null, 2)}</pre>
                    <h3>Parameters</h3>
                    <pre>{JSON.stringify(preview.parameters, null, 2)}</pre>
                    <h3>Input and output schemas</h3>
                    <pre>
                      {JSON.stringify(
                        {
                          inputSchema: selectedDefinition.inputSchema,
                          outputSchema: selectedDefinition.outputSchema,
                        },
                        null,
                        2,
                      )}
                    </pre>
                    <h3>Output details (image data summarized)</h3>
                    <pre>
                      {JSON.stringify(
                        functionPreviewSummary(preview.output),
                        null,
                        2,
                      )}
                    </pre>
                  </details>
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
