"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { McpAppFrame } from "@/modules/artifact-view-host";

import styles from "./workflow-overview.module.css";

type JsonObject = Record<string, unknown>;
type Schema = JsonObject & {
  properties?: JsonObject;
  items?: Schema;
};
type Field = {
  key: string;
  path?: string[];
  label: string;
  description: string | null;
  schemaDescribed?: boolean;
  schema: Schema;
};
type MapItem = {
  index: number;
  itemId: string | null;
  input: unknown;
  output: unknown;
  status: string;
  error: unknown;
  diagnostic: unknown;
};

const rootValueKey = "\u0000value";
const summaryFallbackKey = "\u0000summary-fallback";

function isRecord(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function parseItems(value: unknown): MapItem[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item, position) => {
    if (!isRecord(item)) return [];
    const index = typeof item.index === "number" ? item.index : position;
    return [
      {
        index,
        itemId:
          typeof item.itemId === "string" || typeof item.itemId === "number"
            ? String(item.itemId)
            : null,
        input: item.input ?? item.recordInput,
        output: item.output,
        status: stringValue(item.status) ?? "unknown",
        error: item.error,
        diagnostic: item.diagnostic,
      },
    ];
  });
}

function humanize(key: string) {
  return key
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function fieldsFor(schemaValue: unknown, values: unknown[]): Field[] {
  const schema = isRecord(schemaValue) ? (schemaValue as Schema) : {};
  const properties = isRecord(schema.properties) ? schema.properties : {};
  const keys = [
    ...Object.keys(properties),
    ...values.flatMap((value) => (isRecord(value) ? Object.keys(value) : [])),
  ].filter(
    (key, index, all) =>
      all.indexOf(key) === index &&
      !isTechnicalField(
        key,
        isRecord(properties[key]) ? (properties[key] as Schema) : undefined,
      ),
  );

  if (keys.length === 0) {
    return values.some((value) => value !== undefined)
      ? [
          {
            key: rootValueKey,
            label: stringValue(schema.title) ?? "Value",
            description: stringValue(schema.description),
            schemaDescribed: schemaDescribesValue(schema),
            schema,
          },
        ]
      : [];
  }

  return keys.map((key) => {
    const property = isRecord(properties[key])
      ? (properties[key] as Schema)
      : {};
    return {
      key,
      label: stringValue(property.title) ?? humanize(key),
      description: stringValue(property.description),
      schemaDescribed: schemaDescribesValue(property),
      schema: property,
    };
  });
}

function summaryFieldsFor(schemaValue: unknown, values: unknown[]): Field[] {
  const output: Field[] = [];
  const visit = (
    schemaValueAtPath: unknown,
    currentValues: unknown[],
    path: string[],
    labels: string[],
    depth: number,
  ) => {
    const schema = isRecord(schemaValueAtPath)
      ? (schemaValueAtPath as Schema)
      : {};
    const properties = isRecord(schema.properties) ? schema.properties : {};
    const keys = [
      ...Object.keys(properties),
      ...currentValues.flatMap((value) =>
        isRecord(value) ? Object.keys(value) : [],
      ),
    ].filter((key, index, all) => all.indexOf(key) === index);
    for (const key of keys) {
      const childSchema = isRecord(properties[key])
        ? (properties[key] as Schema)
        : {};
      const childValues = currentValues.map((value) =>
        isRecord(value) ? value[key] : undefined,
      );
      const isNested =
        childSchema.type === "object" ||
        childValues.some((value) => isRecord(value));
      const label = stringValue(childSchema.title) ?? humanize(key);
      if (isNested && depth < 3) {
        if (
          schemaDescribesValue(childSchema) &&
          childValues.some((value) => value !== undefined)
        ) {
          output.push({
            key: [...path, key].join("/"),
            path: [...path, key],
            label: [...labels, label].join(" · "),
            description: stringValue(childSchema.description),
            schemaDescribed: true,
            schema: childSchema,
          });
        } else {
          visit(
            childSchema,
            childValues,
            [...path, key],
            [...labels, label],
            depth + 1,
          );
        }
      } else if (
        childValues.some(
          (value) =>
            value !== undefined &&
            (schemaDescribesValue(childSchema) ||
              Array.isArray(value) ||
              isRecord(value) ||
              value === null ||
              ["string", "number", "boolean"].includes(typeof value)),
        )
      ) {
        output.push({
          key: [...path, key].join("/"),
          path: [...path, key],
          label: [...labels, label].join(" · "),
          description: stringValue(childSchema.description),
          schemaDescribed: schemaDescribesValue(childSchema),
          schema: childSchema,
        });
      }
    }
  };
  visit(schemaValue, values, [], [], 0);
  const useful = output.filter(
    (field) => !isTechnicalField(field.key, field.schema),
  );
  const meaningful = useful.filter((field) =>
    valuesForPath(values, field.path ?? [field.key]).some((value) =>
      isMeaningfulFieldValue(value, field),
    ),
  );
  const priority = (field: Field) => {
    const isCheck = /(^|\/)(checks?|check_results?)(\/|$)/i.test(field.key);
    const isPrimary =
      /(result|value|area|deflection|moment|capacity|passed|safe)/i.test(
        field.key,
      );
    return (
      (schemaMarksPrimary(field.schema) ? -10 : 0) +
      (field.description ? 0 : 5) +
      (isPrimary ? 0 : isCheck ? 8 : 3)
    );
  };
  const schemaFields = meaningful
    .filter((field) => field.schemaDescribed)
    .sort((left, right) => priority(left) - priority(right))
    .slice(0, 3);
  if (schemaFields.length > 0) return schemaFields;

  const namedOutputs = namedScalarOutputFields(values);
  if (namedOutputs.length > 0) return namedOutputs.slice(0, 3);
  const genericFields = meaningful
    .sort((left, right) => priority(left) - priority(right))
    .slice(0, 3);
  if (genericFields.length > 0) return genericFields;
  return values.some((value) => value !== undefined)
    ? [
        {
          key: summaryFallbackKey,
          label: "Result",
          description: null,
          schema: {},
        },
      ]
    : [];
}

function schemaDescribesValue(schema?: Schema) {
  return Boolean(
    stringValue(schema?.title) ||
    stringValue(schema?.description) ||
    schemaMarksPrimary(schema),
  );
}

function schemaMarksPrimary(schema?: Schema) {
  return (
    schema?.primary === true ||
    schema?.["x-primary"] === true ||
    schema?.["x-agent-hub-primary"] === true
  );
}

function isTechnicalField(key: string, schema?: Schema) {
  if (schemaDescribesValue(schema)) return false;
  const normalized = key.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase();
  return /(^|\/)(kind|schema_version|source|source_code|source_hash|source_sha\d*|code|(?:[a-z0-9]+_)?hash|(?:[a-z0-9]+_)?sha\d*|provenance|execution)$/i.test(
    normalized,
  );
}

function valuesForPath(values: unknown[], path: string[]) {
  return values.map((value) => valueAtPath(value, path));
}

function valueAtPath(value: unknown, path: string[]) {
  return path.reduce<unknown>((current, key) => {
    if (isRecord(current)) return current[key];
    if (Array.isArray(current) && /^\d+$/.test(key)) {
      return current[Number(key)];
    }
    return undefined;
  }, value);
}

function isMeaningfulValue(value: unknown) {
  return (
    typeof value === "number" ||
    typeof value === "boolean" ||
    (typeof value === "string" &&
      value.trim() !== "" &&
      value.trim().toLowerCase() !== "not_run")
  );
}

function isMeaningfulFieldValue(value: unknown, field: Field) {
  if (typeof value === "string" && value.trim().toLowerCase() === "not_run") {
    return false;
  }
  return (
    isMeaningfulValue(value) || (field.schemaDescribed && value !== undefined)
  );
}

function namedScalarOutputFields(values: unknown[]): Field[] {
  const candidates = new Map<
    string,
    {
      arrayPath: string[];
      index: number;
      name: string;
      description: string | null;
    }
  >();
  for (const value of values) {
    let visited = 0;
    const visit = (current: unknown, path: string[], depth: number) => {
      if (
        depth > 6 ||
        visited >= 500 ||
        (!isRecord(current) && !Array.isArray(current))
      ) {
        return;
      }
      visited += 1;
      if (Array.isArray(current)) {
        for (
          let index = 0;
          index < current.length && visited < 500;
          index += 1
        ) {
          visit(current[index], [...path, String(index)], depth + 1);
        }
        return;
      }
      for (const [key, nested] of Object.entries(current)) {
        const nestedPath = [...path, key];
        if (key.toLowerCase() === "outputs" && Array.isArray(nested)) {
          for (
            let index = 0;
            index < nested.length && index < 500;
            index += 1
          ) {
            const entry = nested[index];
            if (!isRecord(entry)) continue;
            const name = stringValue(entry.name);
            const result = entry.value;
            if (
              name &&
              !isTechnicalField(name, entry as Schema) &&
              (typeof result === "string" ||
                typeof result === "number" ||
                typeof result === "boolean")
            ) {
              const keyForCandidate = `${nestedPath.join("/")}#${index}`;
              if (!candidates.has(keyForCandidate)) {
                candidates.set(keyForCandidate, {
                  arrayPath: nestedPath,
                  index,
                  name,
                  description: stringValue(entry.description),
                });
              }
            }
          }
        }
        visit(nested, nestedPath, depth + 1);
        if (visited >= 500) break;
      }
    };
    visit(value, [], 0);
  }

  return [...candidates.entries()]
    .filter(([, candidate]) =>
      values.every((value) => {
        const outputArray = valueAtPath(value, candidate.arrayPath);
        if (!Array.isArray(outputArray)) return true;
        if (outputArray.length === 0) return true;
        const entry = outputArray[candidate.index];
        return isRecord(entry) && stringValue(entry.name) === candidate.name;
      }),
    )
    .map(([candidateKey, candidate]) => ({
      key: `${candidateKey}/${candidate.name}`,
      path: [...candidate.arrayPath, String(candidate.index), "value"],
      label: candidate.name,
      description: candidate.description,
      schema: {},
    }))
    .filter((field) =>
      valuesForPath(values, field.path ?? []).some(isMeaningfulValue),
    );
}

function failureReason(error: unknown) {
  const code = stringValue(error);
  if (!code) return "This item failed before producing a saved output.";
  const reasons: Record<string, string> = {
    invalid_mcp_input:
      "The captured input did not match the tool's input schema.",
    invalid_mcp_output:
      "The tool output did not match its saved output schema.",
    missing_structured_output: "The tool did not return structured output.",
    mcp_outcome_unknown: "The tool call ended without a confirmed outcome.",
    plugin_call_limit: "The tool call limit was reached.",
    plugin_unavailable: "The Plugin is unavailable.",
    plugin_not_enabled: "The Plugin is no longer enabled for this Project.",
    plugin_tool_not_allowed: "This tool is not allowed for this Project.",
    plugin_transport_error: "The host could not complete the tool request.",
    stale_target:
      "The Function or tool version used by this Workflow is unavailable.",
    map_input: "The mapped input could not be prepared.",
    map_input_conflict: "The mapped input conflicts with a shared input.",
    runner_unavailable: "The Function runner is unavailable.",
    runner_failed: "The Function runner could not complete this item.",
    input_limit: "The captured input exceeded the Function runner limit.",
    output_limit: "The Function output exceeded the runner limit.",
    runtime_mismatch: "The Function requires a different runner version.",
  };
  return reasons[code] ?? "This item failed while the Workflow was running.";
}

function fieldValue(value: unknown, field: Field) {
  if (field.key === rootValueKey) return value;
  if (field.key === summaryFallbackKey) return "Result available—inspect";
  return valueAtPath(value, field.path ?? [field.key]);
}

function compactValue(value: unknown): string {
  if (value === undefined) return "Not saved";
  if (value === null) return "Null";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value || "Empty";
  if (Array.isArray(value))
    return `${value.length} ${value.length === 1 ? "item" : "items"}`;
  if (isRecord(value)) {
    const count = Object.keys(value).length;
    return `${count} ${count === 1 ? "field" : "fields"}`;
  }
  return String(value);
}

function ValuePreview({ value, schema }: { value: unknown; schema?: Schema }) {
  if (Array.isArray(value)) {
    return (
      <details className={styles.mapNestedValue}>
        <summary>
          {value.length} {value.length === 1 ? "item" : "items"}
        </summary>
        <ol>
          {value.map((item, index) => (
            <li key={index}>
              <ValuePreview value={item} schema={schema?.items} />
            </li>
          ))}
        </ol>
      </details>
    );
  }
  if (isRecord(value)) {
    return (
      <details className={styles.mapNestedValue}>
        <summary>{Object.keys(value).length} fields</summary>
        <dl>
          {Object.entries(value).map(([key, nestedValue]) => {
            const nestedSchema = isRecord(schema?.properties?.[key])
              ? (schema.properties?.[key] as Schema)
              : undefined;
            return (
              <div key={key}>
                <dt>{stringValue(nestedSchema?.title) ?? humanize(key)}</dt>
                <dd>
                  <ValuePreview value={nestedValue} schema={nestedSchema} />
                </dd>
              </div>
            );
          })}
        </dl>
      </details>
    );
  }
  return <span>{compactValue(value)}</span>;
}

function statusLabel(status: string) {
  return status === "succeeded"
    ? "Succeeded"
    : status === "failed"
      ? "Failed"
      : status === "running"
        ? "Running"
        : humanize(status);
}

export function WorkflowMapResults({
  projectId,
  node,
  target,
  items: rawItems,
}: {
  projectId: string;
  node: { id: string; kind: string; refId: string; toolName?: string | null };
  target: JsonObject;
  items: unknown;
}) {
  const items = useMemo(() => parseItems(rawItems), [rawItems]);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [showApp, setShowApp] = useState(false);
  const previewPanelRef = useRef<HTMLElement>(null);
  const previewTriggerRef = useRef<HTMLButtonElement>(null);
  const selectedItem =
    items.find((item) => item.index === selectedIndex) ?? null;
  const inputFields = useMemo(
    () =>
      fieldsFor(
        node.kind === "python" && typeof target.mapInput === "string"
          ? (target.inputSchema as Schema | undefined)?.properties?.[
              target.mapInput
            ]
          : target.inputSchema,
        items.map((item) => item.input),
      ),
    [items, node.kind, target.inputSchema, target.mapInput],
  );
  const outputFields = useMemo(
    () =>
      fieldsFor(
        target.outputSchema,
        items.map((item) => item.output),
      ),
    [items, target.outputSchema],
  );
  const summaryOutputFields = useMemo(
    () =>
      summaryFieldsFor(
        target.outputSchema,
        items.map((item) => item.output),
      ),
    [items, target.outputSchema],
  );
  const selectedOutputFields = useMemo(
    () => summaryFieldsFor(target.outputSchema, [selectedItem?.output]),
    [selectedItem, target.outputSchema],
  );
  const missingDescriptions = [...inputFields, ...outputFields].some(
    (field) => !field.description,
  );
  const pluginId = stringValue(target.pluginId);
  const toolName = stringValue(target.toolName) ?? node.toolName ?? null;
  const version =
    typeof target.version === "string" || typeof target.version === "number"
      ? String(target.version)
      : "";
  const appUrl =
    node.kind === "mcp" && pluginId && toolName && version
      ? `/api/projects/${encodeURIComponent(projectId)}/plugins/${encodeURIComponent(pluginId)}/tools/${encodeURIComponent(toolName)}/app?version=${encodeURIComponent(version)}`
      : null;
  const selectedInput = isRecord(selectedItem?.input)
    ? selectedItem.input
    : { value: selectedItem?.input };
  const selectedOutput = isRecord(selectedItem?.output)
    ? selectedItem.output
    : { value: selectedItem?.output };

  useEffect(() => {
    if (selectedIndex !== null) {
      previewPanelRef.current?.focus();
      return;
    }

    previewTriggerRef.current?.focus();
    previewTriggerRef.current = null;
  }, [selectedIndex]);

  function closePreview() {
    setShowApp(false);
    setSelectedIndex(null);
  }

  return (
    <section aria-label="Mapped item results" className={styles.mapResults}>
      <div className={styles.mapResultsHeading}>
        <div>
          <h3>Results by item</h3>
          <p>
            Primary output values and status are shown here. Preview a row for
            its complete captured input, output, and technical details.
          </p>
        </div>
        <span>{items.length} items</span>
      </div>
      {missingDescriptions ? (
        <p className={styles.mapSchemaGuide}>
          Some fields have no schema description. The view uses their field
          names; ask the Function or MCP Tool author to add descriptions if
          users need more guidance.
        </p>
      ) : null}
      {items.length === 0 ? (
        <p className={styles.mapEmpty}>
          This Run has no saved item results to review.
        </p>
      ) : (
        <div className={styles.mapTableWrap}>
          <table className={styles.mapTable}>
            <thead>
              <tr>
                <th>Item</th>
                {summaryOutputFields.map((field) => (
                  <th
                    key={`output-${field.key}`}
                    title={field.description ?? undefined}
                  >
                    {field.label}
                  </th>
                ))}
                <th>Status</th>
                <th>Inspect</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, position) => (
                <tr key={`${item.index}:${position}`}>
                  <td>
                    <strong>{item.itemId ?? `Item ${item.index + 1}`}</strong>
                  </td>
                  {summaryOutputFields.map((field) => (
                    <td key={`output-${field.key}`}>
                      {item.output === undefined ||
                      (item.status === "failed" && item.output === null)
                        ? "—"
                        : compactValue(fieldValue(item.output, field))}
                    </td>
                  ))}
                  <td>
                    <span
                      className={`${styles.mapStatus} ${item.status === "succeeded" ? styles.mapStatusSucceeded : item.status === "failed" ? styles.mapStatusFailed : ""}`}
                    >
                      {statusLabel(item.status)}
                    </span>
                    {item.status === "failed" ? (
                      <p className={styles.mapNoOutput}>
                        {failureReason(item.error)}
                      </p>
                    ) : null}
                  </td>
                  <td>
                    <button
                      className={styles.mapInspectButton}
                      onClick={(event) => {
                        previewTriggerRef.current = event.currentTarget;
                        setShowApp(false);
                        setSelectedIndex(item.index);
                      }}
                      type="button"
                    >
                      Preview
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selectedItem ? (
        <div
          className={styles.mapPreviewBackdrop}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              closePreview();
            }
          }}
        >
          <aside
            aria-labelledby="map-preview-title"
            aria-modal="true"
            className={styles.mapPreviewPanel}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                closePreview();
                return;
              }
              if (event.key !== "Tab") return;

              const focusable = Array.from(
                previewPanelRef.current?.querySelectorAll<HTMLElement>(
                  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, iframe, [contenteditable="true"], [tabindex]:not([tabindex="-1"])',
                ) ?? [],
              ).filter((element) => element.getClientRects().length > 0);
              if (focusable.length === 0) {
                event.preventDefault();
                previewPanelRef.current?.focus();
                return;
              }

              const first = focusable[0];
              const last = focusable[focusable.length - 1];
              if (
                event.shiftKey &&
                (document.activeElement === first ||
                  document.activeElement === previewPanelRef.current)
              ) {
                event.preventDefault();
                last.focus();
              } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
              }
            }}
            role="dialog"
            ref={previewPanelRef}
            tabIndex={-1}
          >
            <header className={styles.mapPreviewHeader}>
              <div>
                <span>Saved item preview</span>
                <h3 id="map-preview-title">
                  {selectedItem.itemId ?? `Item ${selectedItem.index + 1}`}
                </h3>
              </div>
              <button
                onClick={() => {
                  closePreview();
                }}
                type="button"
              >
                Close
              </button>
            </header>
            <span
              className={`${styles.mapStatus} ${selectedItem.status === "succeeded" ? styles.mapStatusSucceeded : selectedItem.status === "failed" ? styles.mapStatusFailed : ""}`}
            >
              {statusLabel(selectedItem.status)}
            </span>
            {missingDescriptions ? (
              <p className={styles.mapSchemaGuide}>
                Descriptions are optional in the saved schema. Ask the{" "}
                {node.kind === "mcp" ? "MCP Tool" : "Function"} author to add
                them for fields that need more explanation.
              </p>
            ) : null}
            <h4>Inputs</h4>
            <FieldList fields={inputFields} value={selectedItem.input} />
            <h4>Output</h4>
            {selectedItem.output !== undefined ? (
              <FieldList
                fields={selectedOutputFields}
                value={selectedItem.output}
              />
            ) : (
              <p className={styles.mapNoOutput}>
                No output was saved for this item.
              </p>
            )}
            {selectedItem.status === "failed" ? (
              <section aria-label="Failure details">
                <h4>Why it failed</h4>
                <p className={styles.mapNoOutput}>
                  {failureReason(selectedItem.error)}
                </p>
                <details className={styles.mapTechnicalDetails}>
                  <summary>Exact error</summary>
                  <pre>
                    {selectedItem.error === undefined
                      ? "No technical error was saved for this item."
                      : typeof selectedItem.error === "string"
                        ? selectedItem.error
                        : JSON.stringify(selectedItem.error, null, 2)}
                    {selectedItem.diagnostic !== undefined
                      ? `\n\nDiagnostic:\n${typeof selectedItem.diagnostic === "string" ? selectedItem.diagnostic : JSON.stringify(selectedItem.diagnostic, null, 2)}`
                      : ""}
                  </pre>
                </details>
              </section>
            ) : null}
            <details className={styles.mapTechnicalDetails}>
              <summary>Complete captured input and output</summary>
              <h4>Input</h4>
              <ValuePreview value={selectedItem.input} />
              <h4>Output</h4>
              {selectedItem.output !== undefined ? (
                <ValuePreview value={selectedItem.output} />
              ) : (
                <p>No output was saved for this item.</p>
              )}
            </details>
            <details className={styles.mapTechnicalDetails}>
              <summary>Technical details and provenance</summary>
              <p>
                Item ID:{" "}
                {selectedItem.itemId ?? `Item ${selectedItem.index + 1}`}
              </p>
              <pre>{JSON.stringify(target, null, 2)}</pre>
            </details>
            {appUrl && selectedItem.status === "succeeded" ? (
              <section className={styles.mapAppPreview}>
                <div>
                  <h4>Interactive view</h4>
                  <p>
                    Open the MCP App with this saved input and result. The tool
                    will not run again.
                  </p>
                </div>
                {!showApp ? (
                  <button onClick={() => setShowApp(true)} type="button">
                    Open MCP App
                  </button>
                ) : (
                  <McpAppFrame
                    appUrl={appUrl}
                    key={selectedItem.index}
                    title={`${toolName ?? "MCP Tool"} result preview`}
                    toolInput={selectedInput}
                    toolResult={{
                      content: [],
                      structuredContent: selectedOutput,
                    }}
                  />
                )}
              </section>
            ) : null}
          </aside>
        </div>
      ) : null}
    </section>
  );
}

function FieldList({ fields, value }: { fields: Field[]; value: unknown }) {
  if (fields.length === 0) {
    const recordKeys = isRecord(value) ? Object.keys(value) : [];
    if (
      recordKeys.length > 0 &&
      recordKeys.every((key) => isTechnicalField(key))
    ) {
      return (
        <p className={styles.mapNoOutput}>
          This saved value contains technical fields only. Open complete
          captured input and output below to inspect them.
        </p>
      );
    }
    return (
      <div className={styles.mapFieldList}>
        <div>
          <dt>Value</dt>
          <dd>
            <ValuePreview value={value} />
          </dd>
        </div>
      </div>
    );
  }

  return (
    <dl className={styles.mapFieldList}>
      {fields.map((field) => (
        <div key={field.key}>
          <dt>{field.label}</dt>
          <dd>
            <ValuePreview
              value={fieldValue(value, field)}
              schema={field.schema}
            />
          </dd>
          {field.description ? (
            <p>{field.description}</p>
          ) : (
            <p className={styles.mapMissingDescription}>
              No description in the saved schema. Add one to guide users.
            </p>
          )}
        </div>
      ))}
    </dl>
  );
}
