"use client";

import { useState } from "react";

import type { ProposedFileReview } from "./_approval";
import styles from "./file-proposal-preview.module.css";

export function ProposedFilePreview({
  proposal,
}: {
  proposal: ProposedFileReview;
}) {
  const [tab, setTab] = useState<"diff" | "file">(
    proposal.kind === "diff" ? "diff" : "file",
  );
  const activeTab = proposal.kind === "preview" ? "file" : tab;

  return (
    <section aria-label="Proposed Project File" className={styles.preview}>
      <header className={styles.header}>
        <strong>Proposed Project File</strong>
        <code>{proposal.path}</code>
        <span>Not the saved Project file · review snapshot</span>
      </header>
      {proposal.kind === "diff" ? (
        <div aria-label="Proposed file views" className={styles.tabs}>
          <button
            aria-pressed={activeTab === "diff"}
            onClick={() => setTab("diff")}
            type="button"
          >
            Diff
          </button>
          <button
            aria-pressed={activeTab === "file"}
            onClick={() => setTab("file")}
            type="button"
          >
            Proposed file
          </button>
        </div>
      ) : null}
      {activeTab === "diff" ? (
        <pre aria-label="Proposed file diff" className={styles.content}>
          {proposal.text.split("\n").map((line, index) => (
            <span
              className={
                line.startsWith("+") && !line.startsWith("+++")
                  ? styles.added
                  : line.startsWith("-") && !line.startsWith("---")
                    ? styles.removed
                    : line.startsWith("@@")
                      ? styles.hunk
                      : undefined
              }
              key={index}
            >
              {line}
            </span>
          ))}
        </pre>
      ) : (
        <pre aria-label="Proposed file content" className={styles.content}>
          {proposal.proposed}
        </pre>
      )}
      <footer>
        Open the Project file to inspect its current saved content.
      </footer>
    </section>
  );
}
