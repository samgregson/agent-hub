import { prepareExecutionDocument } from "@cs-object/react";
import { PreparedFormulaSheet } from "@cs-object/react";
import * as React from "react";
import { createRoot } from "react-dom/client";
import { createElement, useEffect, useMemo, useState } from "react";
import type { ReactElement } from "react";
import styles from "@cs-object/react/style.css";

const style = document.createElement("style");
style.textContent = styles;
document.head.append(style);

type Snapshot = {
  artifact?: { title?: string };
  payload?: {
    input?: {
      source?: string;
      function?: string;
      inputs?: Record<string, number>;
    };
    output?: {
      kind?: string;
      sourceSha256?: string;
      execution?: unknown;
    };
  };
};

function Report({ snapshot }: { snapshot: Snapshot }): ReactElement {
  const input = snapshot.payload?.input;
  const output = snapshot.payload?.output;
  const execution = output?.execution;
  const prepared = useMemo((): {
    document: unknown;
    failure: string | null;
  } => {
    if (!execution) return { document: null, failure: null };
    try {
      return {
        document: prepareExecutionDocument({
          execution: execution as never,
          assets: [],
        }),
        failure: null,
      };
    } catch (error) {
      return {
        document: null,
        failure:
          error instanceof Error
            ? error.message
            : "Could not prepare this report.",
      };
    }
  }, [execution]);

  return (
    <main>
      <header className="page-header">
        <p className="eyebrow">Calculation Source Object</p>
        <h1>{snapshot.artifact?.title || "Calculation report"}</h1>
        <div className="meta">
          {input?.function
            ? `Function: ${input.function}`
            : "Captured execution"}
          {output?.sourceSha256
            ? ` · Source SHA-256: ${output.sourceSha256}`
            : ""}
        </div>
      </header>
      <aside className="notice">
        This view presents a captured execution. Formula consistency,
        independent reference agreement, and engineering suitability have not
        been established by this run.
      </aside>
      {input?.inputs && Object.keys(input.inputs).length > 0 ? (
        <section aria-label="Captured inputs" className="inputs">
          {Object.entries(input.inputs).map(([name, value]) => (
            <span className="input" key={name}>
              <b>{name}</b>
              <code>{value}</code>
            </span>
          ))}
        </section>
      ) : null}
      {prepared.document ? (
        <section className="cso-document">
          <PreparedFormulaSheet
            document={prepared.document as never}
            showSourceDetails={false}
          />
        </section>
      ) : (
        <p className="error" role="alert">
          {prepared.failure ||
            "This Artifact does not contain a supported CalculationSourceObject execution."}
        </p>
      )}
      {input?.source ? (
        <details>
          <summary>View captured Python source</summary>
          <pre>{input.source}</pre>
        </details>
      ) : null}
    </main>
  );
}

function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toolInput = React.useRef<Record<string, unknown>>({});

  useEffect(() => {
    const listener = (event: MessageEvent) => {
      const message = event.data;
      if (
        message?.id === "calculation-source-object-initialize" &&
        message.result
      ) {
        window.parent.postMessage(
          {
            jsonrpc: "2.0",
            method: "ui/notifications/initialized",
            params: {},
          },
          "*",
        );
      }
      if (message?.method === "ui/notifications/tool-input") {
        const arguments_ = message.params?.arguments;
        if (
          arguments_ &&
          typeof arguments_ === "object" &&
          !Array.isArray(arguments_)
        ) {
          toolInput.current = arguments_ as Record<string, unknown>;
        }
      }
      if (message?.method === "ui/notifications/tool-result") {
        const result = message.params?.structuredContent as
          Record<string, unknown> | undefined;
        const savedDocument = result?.payload as
          Snapshot["payload"] | undefined;
        if (
          savedDocument?.output?.kind === "calculation-source-object.execution"
        ) {
          setSnapshot(result as Snapshot);
          setError(null);
        } else if (result?.kind === "calculation-source-object.execution") {
          setSnapshot({
            payload: { input: toolInput.current, output: result },
          });
          setError(null);
        } else {
          setError(
            "The saved result is not a CalculationSourceObject execution.",
          );
        }
      }
    };
    window.addEventListener("message", listener);
    window.parent.postMessage(
      {
        jsonrpc: "2.0",
        id: "calculation-source-object-initialize",
        method: "ui/initialize",
        params: {
          appInfo: { name: "Calculation Source Object", version: "0.1.0" },
          appCapabilities: {},
          protocolVersion: "2026-01-26",
        },
      },
      "*",
    );
    return () => window.removeEventListener("message", listener);
  }, []);

  if (error)
    return (
      <p className="error" role="alert">
        {error}
      </p>
    );
  if (!snapshot) return <p>Loading saved calculation…</p>;
  return <Report snapshot={snapshot} />;
}

createRoot(document.getElementById("root")!).render(createElement(App));
