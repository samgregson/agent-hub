"use client";

import { useEffect, useState } from "react";

import type { ArtifactCatalog as Catalog } from "@/contracts";

import styles from "./artifact-view-host.module.css";

interface CatalogResult {
  catalog: Catalog | null;
  error: string | null;
  projectId: string;
}

export function ArtifactCatalog({
  onOpen,
  projectId,
}: {
  onOpen: (artifactId: string) => void;
  projectId: string;
}) {
  const [result, setResult] = useState<CatalogResult>({
    catalog: null,
    error: null,
    projectId: "",
  });
  const catalog = result.projectId === projectId ? result.catalog : null;
  const error = result.projectId === projectId ? result.error : null;

  useEffect(() => {
    let active = true;
    fetch(`/api/projects/${encodeURIComponent(projectId)}/artifacts`, {
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status));
        return (await response.json()) as Catalog;
      })
      .then((result) => {
        if (active) setResult({ catalog: result, error: null, projectId });
      })
      .catch(() => {
        if (active) {
          setResult({
            catalog: null,
            error: "Artifacts are temporarily unavailable.",
            projectId,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [projectId]);

  return (
    <section className={styles.catalog}>
      {error ? <p className={styles.error}>{error}</p> : null}
      {!catalog && !error ? <p>Loading Artifacts…</p> : null}
      {catalog?.artifacts.map((artifact) => (
        <button
          key={artifact.id}
          onClick={() => onOpen(artifact.id)}
          type="button"
        >
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
