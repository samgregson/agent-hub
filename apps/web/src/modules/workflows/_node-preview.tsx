import styles from "./workflow-node-preview.module.css";
import {
  ImageOutputPreview,
  imageDataUrl,
  isImageOutput,
} from "@/modules/media";

export type WorkflowNodePreviewNode = {
  id: string;
  kind: string;
  refId: string;
  version: number | string;
  shape?: string;
};

export type WorkflowNodePreviewSource = {
  label: string;
  value: unknown;
  provenance?: string;
};

export type WorkflowNodePreviewProps = {
  node: WorkflowNodePreviewNode;
  kindLabel: string;
  inputs?: unknown;
  inputSources?: WorkflowNodePreviewSource[];
  capturedTarget?: unknown;
  output?: unknown;
  outputState?: "available" | "loading" | "unavailable" | "error";
  outputError?: unknown;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function json(value: unknown) {
  if (value === undefined) return "No value captured";
  try {
    return JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    return String(value);
  }
}

function scalar(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean")
    return String(value);
  return json(value);
}

function summarize(value: unknown): string {
  if (Array.isArray(value)) return `${value.length} items`;
  if (isRecord(value)) return `${Object.keys(value).length} fields`;
  if (typeof value === "string" && (value.length > 120 || value.includes("\n")))
    return `Text · ${value.length} characters`;
  return scalar(value);
}

function PreviewValue({ value }: { value: unknown }) {
  if (isImageOutput(value)) {
    return (
      <ImageOutputPreview
        altText={value.altText}
        src={imageDataUrl(value)}
        title="Image output"
      />
    );
  }
  if (Array.isArray(value) && value.length > 0 && value.every(isRecord)) {
    const columns = [...new Set(value.slice(0, 20).flatMap(Object.keys))].slice(
      0,
      5,
    );
    return (
      <div className={styles.tableWrap}>
        <table>
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {value.slice(0, 4).map((row, index) => (
              <tr key={index}>
                {columns.map((column) => (
                  <td key={column}>{scalar(row[column])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {value.length > 4 && (
          <p className={styles.truncation}>Showing 4 of {value.length} rows</p>
        )}
      </div>
    );
  }
  if (Array.isArray(value)) {
    return (
      <ol className={styles.valueList}>
        {value.slice(0, 4).map((item, index) => (
          <li key={index}>{scalar(item)}</li>
        ))}
      </ol>
    );
  }
  if (isRecord(value)) {
    return (
      <dl className={styles.fields}>
        {Object.entries(value)
          .slice(0, 6)
          .map(([key, item]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{summarize(item)}</dd>
            </div>
          ))}
        {Object.keys(value).length > 6 && (
          <p className={styles.truncation}>
            Showing 6 of {Object.keys(value).length} fields
          </p>
        )}
      </dl>
    );
  }
  const displayValue =
    value === undefined ? "No value captured" : scalar(value);
  const shortened =
    displayValue.length > 360 ? `${displayValue.slice(0, 360)}…` : displayValue;
  return (
    <>
      <p className={styles.primitive}>{shortened}</p>
      {shortened !== displayValue && (
        <p className={styles.truncation}>
          Preview shortened · full value below
        </p>
      )}
    </>
  );
}

function Detail({ label, value }: { label: string; value: unknown }) {
  return (
    <details className={styles.detail}>
      <summary>View full {label.toLowerCase()}</summary>
      <pre>{json(value)}</pre>
    </details>
  );
}

export function WorkflowNodePreview({
  node,
  kindLabel,
  inputs,
  inputSources = [],
  capturedTarget,
  output,
  outputState = output === undefined ? "unavailable" : "available",
  outputError,
}: WorkflowNodePreviewProps) {
  const sources =
    inputSources.length > 0
      ? inputSources
      : [
          {
            label: "Resolved inputs",
            value: inputs,
            provenance: "Captured for this Run",
          },
        ];

  return (
    <section aria-label={`${node.id} details`} className={styles.preview}>
      <header className={styles.header}>
        <div>
          <h2>{node.id}</h2>
          <p>
            {kindLabel} · {node.refId} · v{node.version}
          </p>
        </div>
        {node.shape === "map" && (
          <span className={styles.mapTag}>Map step</span>
        )}
      </header>
      <div className={styles.columns}>
        <section className={styles.port} aria-label="Node output">
          <div className={styles.portHeading}>
            <span className={styles.outputMark} aria-hidden="true" />
            <h3>Output</h3>
          </div>
          {outputState === "loading" ? (
            <p className={styles.state}>Loading this step’s output…</p>
          ) : null}
          {outputState === "unavailable" ? (
            <p className={styles.state}>
              No output is available for this step in the selected Run.
            </p>
          ) : null}
          {outputState === "error" ? (
            <div className={styles.error}>
              <strong>Step failed</strong>
              <p>
                {outputError === undefined
                  ? "The Run did not produce an output."
                  : scalar(outputError)}
              </p>
            </div>
          ) : null}
          {outputState === "available" ? (
            <article className={styles.value}>
              <div className={styles.valueHeading}>
                <strong>Step result</strong>
                <span>Saved in this Run</span>
              </div>
              <PreviewValue value={output} />
              <Detail label="output" value={output} />
            </article>
          ) : null}
        </section>
        <section className={styles.port} aria-label="Node inputs">
          <div className={styles.portHeading}>
            <span className={styles.inputMark} aria-hidden="true" />
            <h3>Inputs</h3>
          </div>
          {sources.map((source, index) => (
            <article className={styles.value} key={`${source.label}-${index}`}>
              <div className={styles.valueHeading}>
                <strong>{source.label}</strong>
                <span>{source.provenance ?? "Workflow binding"}</span>
              </div>
              <PreviewValue value={source.value} />
              <Detail label={source.label} value={source.value} />
            </article>
          ))}
          {capturedTarget !== undefined && (
            <Detail label="captured target" value={capturedTarget} />
          )}
        </section>
      </div>
    </section>
  );
}
