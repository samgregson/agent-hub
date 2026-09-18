"use client";

import { useEffect, useState } from "react";

import type { ProjectFileCatalog as Catalog } from "@/contracts";

import styles from "./project-files.module.css";

export function ProjectFileCatalog({
  onOpen,
  projectId,
}: {
  onOpen: (path: string) => void;
  projectId: string;
}) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);

  useEffect(() => {
    let active = true;
    fetch(`/api/projects/${encodeURIComponent(projectId)}/files/index`, {
      cache: "no-store",
    })
      .then((response) => (response.ok ? response.json() : Promise.reject()))
      .then((result: Catalog) => active && setCatalog(result))
      .catch(() => active && setCatalog({ files: [] }));
    return () => {
      active = false;
    };
  }, [projectId]);

  return (
    <section aria-label="Project files" className={styles.catalog}>
      <strong>Project files</strong>
      {!catalog ? <p>Loading files…</p> : null}
      {catalog?.files.map((file) => (
        <button key={file.path} onClick={() => onOpen(file.path)} type="button">
          <code>{file.path}</code>
          <span>Version {file.version}</span>
        </button>
      ))}
      {catalog?.files.length === 0 ? <p>No Project files yet.</p> : null}
    </section>
  );
}
