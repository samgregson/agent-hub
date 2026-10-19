"use client";

import { useEffect, useMemo, useState } from "react";

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
  schema: Schema;
};
type MapItem = {
  index: number;
  itemId: string | null;
  input: unknown;
  output: unknown;
  status: string;
};

const rootValueKey = "\u0000value";

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
  ].filter((key, index, all) => all.indexOf(key) === index);

  if (keys.length === 0) {
    return values.some((value) => value !== undefined)
      ? [
          {
            key: rootValueKey,
            label: stringValue(schema.title) ?? "Value",
            description: stringValue(schema.description),
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
        visit(
          childSchema,
          childValues,
          [...path, key],
          [...labels, label],
          depth + 1,
        );
      } else if (
        childValues.some(
          (value) =>
            value !== undefined &&
            (value === null ||
              ["string", "number", "boolean"].includes(typeof value)),
        )
      ) {
        output.push({
          key: [...path, key].join("/"),
          path: [...path, key],
          label: [...labels, label].join(" · "),
          description: stringValue(childSchema.description),
          schema: childSchema,
        });
      }
    }
  };
  visit(schemaValue, values, [], [], 0);
  const useful = output.filter(
    (field) =>
      !/(^|\/)(source|source_code|source_hash|code|hash|sha|provenance|execution)$/i.test(
        field.key,
      ),
  );
  const priority = (field: Field) =>
    /(check|warning|result|value|area|deflection|moment|capacity|passed|safe|status)/i.test(
      field.key,
    )
      ? 0
      : field.description
        ? 1
        : 2;
  return useful
    .sort((left, right) => priority(left) - priority(right))
    .slice(0, 3);
}

function fieldValue(value: unknown, field: Field) {
  if (field.key === rootValueKey) return value;
  return (field.path ?? [field.key]).reduce<unknown>(
    (current, key) => (isRecord(current) ? current[key] : undefined),
    value,
  );
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
    if (selectedIndex === null) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setShowApp(false);
        setSelectedIndex(null);
      }
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [selectedIndex]);

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
                      {item.output === undefined
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
                  </td>
                  <td>
                    <button
                      className={styles.mapInspectButton}
                      onClick={() => {
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
              setShowApp(false);
              setSelectedIndex(null);
            }
          }}
        >
          <aside
            aria-labelledby="map-preview-title"
            aria-modal="true"
            className={styles.mapPreviewPanel}
            role="dialog"
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
                  setShowApp(false);
                  setSelectedIndex(null);
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
              <FieldList fields={outputFields} value={selectedItem.output} />
            ) : (
              <p className={styles.mapNoOutput}>
                No output was saved for this item.
              </p>
            )}
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
