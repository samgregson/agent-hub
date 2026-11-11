"use client";

import { useEffect, useRef, useState } from "react";

import styles from "./workflow-overview.module.css";

type FunctionDefinition = {
  source?: string;
  inputSchema?: Record<string, unknown>;
  outputSchema?: Record<string, unknown>;
};

export function WorkflowFunctionPreview({
  projectId,
  functionId,
  version,
  capturedTarget,
}: {
  projectId: string;
  functionId: string;
  version: number | string;
  capturedTarget: Record<string, unknown>;
}) {
  const capturedSource =
    typeof capturedTarget.source === "string" ? capturedTarget.source : null;
  const capturedInputSchema = capturedTarget.inputSchema;
  const capturedOutputSchema = capturedTarget.outputSchema;
  const [definition, setDefinition] = useState<FunctionDefinition | null>(null);
  const [expanded, setExpanded] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (capturedSource !== null) {
      setDefinition({
        source: capturedSource,
        inputSchema: capturedInputSchema as Record<string, unknown>,
        outputSchema: capturedOutputSchema as Record<string, unknown>,
      });
      return;
    }
    let active = true;
    void fetch(
      `/api/projects/${encodeURIComponent(projectId)}/functions/${encodeURIComponent(functionId)}`,
      { cache: "no-store" },
    )
      .then((response) => {
        if (!response.ok) throw new Error("Function unavailable");
        return response.json() as Promise<FunctionDefinition>;
      })
      .then((loaded) => {
        if (active) setDefinition(loaded);
      })
      .catch(() => {
        if (active) setDefinition(null);
      });
    return () => {
      active = false;
    };
  }, [
    capturedInputSchema,
    capturedOutputSchema,
    capturedSource,
    functionId,
    projectId,
  ]);

  useEffect(() => {
    if (expanded && dialog.current && !dialog.current.open) {
      dialog.current.showModal();
    }
  }, [expanded]);

  const source = definition?.source ?? "Function source is unavailable.";
  return (
    <section
      className={styles.functionSourcePreview}
      aria-label="Python Function preview"
    >
      <header>
        <div>
          <h2>Python Function</h2>
          <p>
            {functionId} · version {version}
          </p>
        </div>
        <button onClick={() => setExpanded(true)} type="button">
          View full
        </button>
      </header>
      <pre>{source}</pre>
      <details>
        <summary>Function inputs and outputs</summary>
        <pre>
          {JSON.stringify(
            {
              inputs: definition?.inputSchema,
              outputs: definition?.outputSchema,
            },
            null,
            2,
          )}
        </pre>
      </details>
      {expanded ? (
        <dialog
          ref={dialog}
          aria-label="Full Python Function"
          className={styles.functionSourceDialog}
          onClose={() => setExpanded(false)}
        >
          <header>
            <strong>{functionId}</strong>
            <button onClick={() => dialog.current?.close()} type="button">
              Close
            </button>
          </header>
          <pre>{source}</pre>
        </dialog>
      ) : null}
    </section>
  );
}
