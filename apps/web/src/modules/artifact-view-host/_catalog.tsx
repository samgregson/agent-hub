"use client";

import { useEffect, useState } from "react";

import type { ArtifactCatalog as Catalog } from "@/contracts";

import styles from "./artifact-view-host.module.css";

export function ArtifactCatalog({
  onOpen,
  projectId,
}: {
  onOpen: (artifactId: string) => void;
  projectId: string;
}) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setCatalog(null);
    setError(null);
    fetch(`/api/projects/${encodeURIComponent(projectId)}/artifacts`, {
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status));
        return (await response.json()) as Catalog;
      })
      .then((result) => {
        if (active) setCatalog(result);
      })
      .catch(() => {
        if (active) setError("Artifacts are temporarily unavailable.");
      });
    return () => {
      active = false;
    };
  }, [projectId]);

  return (
    <section className={styles.catalog}>
      <strong>Artifacts</strong>
      <p>Durable project work products. Project files appear below until elevated.</p>
      {error ? <p className={styles.error}>{error}</p> : null}
      {!catalog && !error ? <p>Loading Artifacts…</p> : null}
      {catalog?.artifacts.map((artifact) => (
        <button key={artifact.id} onClick={() => onOpen(artifact.id)} type="button">
          <span>{artifact.title}</span>
          <small>
            {artifact.type} · v{artifact.documentVersion}
          </small>
        </button>
      ))}
      {catalog?.artifacts.length === 0 ? <p>No Artifacts yet.</p> : null}
    </section>
  );
}
