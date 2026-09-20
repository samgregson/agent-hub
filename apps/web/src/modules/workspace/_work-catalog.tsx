"use client";

import { useEffect, useState } from "react";

import type { ArtifactCatalog, ProjectFileCatalog } from "@/contracts";

import styles from "./workspace.module.css";

type WorkItem =
  | { id: string; kind: "artifact"; label: string; version: number }
  | { kind: "projectFile"; label: string; path: string; version: number };

interface WorkCatalogResult {
  error: string | null;
  items: WorkItem[] | null;
  projectId: string;
}

function combineWorkItems(
  artifacts: ArtifactCatalog,
  files: ProjectFileCatalog,
): WorkItem[] {
  return [
    ...artifacts.artifacts.map((artifact) => ({
      id: artifact.id,
      kind: "artifact" as const,
      label: artifact.title,
      version: artifact.documentVersion,
    })),
    ...files.files.map((file) => ({
      kind: "projectFile" as const,
      label: file.path,
      path: file.path,
      version: file.version,
    })),
  ].sort((left, right) => left.label.localeCompare(right.label));
}

export function WorkCatalog({
  onOpenArtifact,
  onOpenProjectFile,
  projectId,
}: {
  onOpenArtifact: (artifactId: string) => void;
  onOpenProjectFile: (path: string) => void;
  projectId: string;
}) {
  const [result, setResult] = useState<WorkCatalogResult>({
    error: null,
    items: null,
    projectId: "",
  });
  const items = result.projectId === projectId ? result.items : null;
  const error = result.projectId === projectId ? result.error : null;

  useEffect(() => {
    let active = true;
    const encodedProjectId = encodeURIComponent(projectId);
    Promise.all([
      fetch(`/api/projects/${encodedProjectId}/artifacts`, {
        cache: "no-store",
      }),
      fetch(`/api/projects/${encodedProjectId}/files/index`, {
        cache: "no-store",
      }),
    ])
      .then(async ([artifactResponse, fileResponse]) => {
        if (!artifactResponse.ok || !fileResponse.ok) {
          throw new Error("Work catalog unavailable");
        }
        return combineWorkItems(
          (await artifactResponse.json()) as ArtifactCatalog,
          (await fileResponse.json()) as ProjectFileCatalog,
        );
      })
      .then((loaded) => {
        if (active) setResult({ error: null, items: loaded, projectId });
      })
      .catch(() => {
        if (active) {
          setResult({
            error: "Work items are temporarily unavailable.",
            items: null,
            projectId,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [projectId]);

  return (
    <section aria-label="Work items" className={styles.workCatalog}>
      {error ? <p className={styles.error}>{error}</p> : null}
      {!items && !error ? <p>Loading work…</p> : null}
      {items?.map((item) => (
        <button
          key={item.kind === "artifact" ? item.id : item.path}
          onClick={() =>
            item.kind === "artifact"
              ? onOpenArtifact(item.id)
              : onOpenProjectFile(item.path)
          }
          type="button"
        >
          <span>{item.label}</span>
          <small>Version {item.version}</small>
        </button>
      ))}
      {items?.length === 0 ? <p>No work items yet.</p> : null}
    </section>
  );
}
