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
  onSavedToProject,
  path,
  projectId,
  threadId,
}: {
  onSavedToProject: (path: string) => void;
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
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

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

  async function saveToProject() {
    const destinationPath = window.prompt(
      "Save scratch file to Project",
      `/project${path.replace(/^\/scratch/, "")}`,
    );
    if (destinationPath === null) return;
    setIsSaving(true);
    setSaveError(null);
    try {
      const response = await fetch(
        `/api/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(threadId)}/scratch/save`,
        {
          body: JSON.stringify({ destinationPath, sourcePath: path }),
          headers: { "content-type": "application/json" },
          method: "POST",
        },
      );
      if (!response.ok) throw new Error(String(response.status));
      const saved = (await response.json()) as { path: string };
      onSavedToProject(saved.path);
    } catch {
      setSaveError(
        "This scratch file could not be saved. Choose an unused /project/ path and try again.",
      );
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <section className={styles.filePreview}>
      <header>
        <strong>Thread-local scratch file</strong>
        <code>{path}</code>
      </header>
      {error ? <p className={styles.runError}>{error}</p> : null}
      {!file && !error ? <p>Opening file…</p> : null}
      {file ? <pre>{file.content}</pre> : null}
      {file ? (
        <button
          className={styles.saveScratch}
          disabled={isSaving}
          onClick={() => void saveToProject()}
          type="button"
        >
          {isSaving ? "Saving…" : "Save to Project"}
        </button>
      ) : null}
      {saveError ? <p className={styles.runError}>{saveError}</p> : null}
      <footer>
        Thread-only working material. Scratch files stay out of Project-wide
        files and deliverables.
      </footer>
    </section>
  );
}
