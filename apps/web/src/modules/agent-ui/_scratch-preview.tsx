"use client";

import { useEffect, useState } from "react";

import type { ScratchFilePreview as ScratchFilePreviewContract } from "@/contracts";

import styles from "./agent-ui.module.css";

interface PreviewResult {
  error: string | null;
  file: ScratchFilePreviewContract | null;
  key: string;
}

export function ScratchFilePreview({
  path,
  projectId,
  threadId,
}: {
  path: string;
  projectId: string;
  threadId: string;
}) {
  const key = `${projectId}:${threadId}:${path}`;
  const [result, setResult] = useState<PreviewResult>({
    error: null,
    file: null,
    key: "",
  });
  const file = result.key === key ? result.file : null;
  const error = result.key === key ? result.error : null;

  useEffect(() => {
    let active = true;
    fetch(
      `/api/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(threadId)}/scratch?path=${encodeURIComponent(path)}`,
      { cache: "no-store" },
    )
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status));
        return (await response.json()) as ScratchFilePreviewContract;
      })
      .then((loaded) => {
        if (active) setResult({ error: null, file: loaded, key });
      })
      .catch(() => {
        if (active) {
          setResult({
            error: "This Thread-local scratch file could not be opened.",
            file: null,
            key,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [key, path, projectId, threadId]);

  return (
    <section className={styles.filePreview}>
      <header>
        <strong>Thread-local scratch file</strong>
        <code>{path}</code>
      </header>
      {error ? <p className={styles.runError}>{error}</p> : null}
      {!file && !error ? <p>Opening file…</p> : null}
      {file ? <pre>{file.content}</pre> : null}
      <footer>
        Thread-only working material. Scratch files stay out of Project-wide
        files and deliverables.
      </footer>
    </section>
  );
}
