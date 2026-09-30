"use client";

import { useEffect, useState } from "react";

import type { ProjectFilePreview } from "@/contracts";

import styles from "./project-files.module.css";

interface PreviewResult {
  error: string | null;
  file: ProjectFilePreview | null;
  key: string;
}

export function ProjectFilePreview({
  path,
  projectId,
}: {
  path: string;
  projectId: string;
}) {
  const key = `${projectId}:${path}`;
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
      `/api/projects/${encodeURIComponent(projectId)}/files?path=${encodeURIComponent(path)}`,
      { cache: "no-store" },
    )
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status));
        return (await response.json()) as ProjectFilePreview;
      })
      .then((loaded) => {
        if (active) setResult({ error: null, file: loaded, key });
      })
      .catch(() => {
        if (active) {
          setResult({
            error: "This Project file could not be opened.",
            file: null,
            key,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [key, path, projectId]);

  return (
    <section className={styles.preview}>
      <header>
        <strong>Project file</strong>
        <code>{path}</code>
        {file ? <span>Version {file.version}</span> : null}
      </header>
      {error ? <p className={styles.error}>{error}</p> : null}
      {!file && !error ? <p>Opening file…</p> : null}
      {file ? <pre>{file.content}</pre> : null}
      <footer>
        Shared working material for this Project. Publish an Artifact when the
        result needs a type, provenance, and a dedicated view.
      </footer>
    </section>
  );
}
