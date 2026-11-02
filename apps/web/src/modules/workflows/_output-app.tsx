"use client";

import { useState } from "react";
import { McpAppFrame } from "@/modules/artifact-view-host";
import styles from "./workflow-overview.module.css";

export function WorkflowOutputApp({
  appUrl,
  title,
  inputs,
  output,
}: {
  appUrl: string;
  title: string;
  inputs: Record<string, unknown>;
  output: Record<string, unknown>;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        className={styles.secondaryButton}
        type="button"
        onClick={() => setOpen(!open)}
      >
        {open ? "Close App" : "Open App"}
      </button>
      {open ? (
        <McpAppFrame
          appUrl={appUrl}
          title="Workflow output App"
          displayTitle={title}
          toolInput={inputs}
          toolResult={{ content: [], structuredContent: output }}
        />
      ) : null}
      <details>
        <summary>Output data</summary>
        <pre>{JSON.stringify(output, null, 2)}</pre>
      </details>
    </>
  );
}
