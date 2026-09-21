"use client";

import { useEffect, useState } from "react";

import type { ArtifactCatalog, ProjectFileCatalog } from "@/contracts";
import { Menu, MenuItem } from "@/shared/ui";

import styles from "./workspace.module.css";

type WorkItem =
  | { id: string; kind: "artifact"; label: string; version: number }
  | { kind: "projectFile"; label: string; path: string; version: number };

type PendingDeletion = WorkItem | null;

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
  const [pendingDeletion, setPendingDeletion] = useState<PendingDeletion>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const items = result.projectId === projectId ? result.items : null;
  const error = result.projectId === projectId ? result.error : null;

  async function deleteItem(item: WorkItem) {
    setIsDeleting(true);
    setDeleteError(null);
    try {
      const encodedProjectId = encodeURIComponent(projectId);
      const response =
        item.kind === "artifact"
          ? await fetch(
              `/api/projects/${encodedProjectId}/artifacts/${encodeURIComponent(item.id)}`,
              { method: "DELETE" },
            )
          : await fetch(
              `/api/projects/${encodedProjectId}/files?path=${encodeURIComponent(item.path)}`,
              { method: "DELETE" },
            );
      if (!response.ok) throw new Error(String(response.status));
      setResult((current) =>
        current.projectId !== projectId || current.items === null
          ? current
          : {
              ...current,
              items: current.items.filter((candidate) => candidate !== item),
            },
      );
      setPendingDeletion(null);
    } catch {
      setDeleteError("Deletion failed. Please try again.");
    } finally {
      setIsDeleting(false);
    }
  }

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
        <div
          className={styles.workItem}
          key={item.kind === "artifact" ? item.id : item.path}
        >
          <button
            aria-label={item.label}
            className={styles.workItemOpen}
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
          <Menu label={`${item.label} actions`}>
            <MenuItem
              destructive
              onSelect={() => {
                setDeleteError(null);
                setPendingDeletion(item);
              }}
            >
              Delete
            </MenuItem>
          </Menu>
        </div>
      ))}
      {items?.length === 0 ? <p>No work items yet.</p> : null}
      {pendingDeletion ? (
        <dialog
          aria-label="Confirm deletion"
          className={styles.deleteDialog}
          open
        >
          <p className={styles.deleteDialogEyebrow}>Permanent removal</p>
          <h2>
            Delete this{" "}
            {pendingDeletion.kind === "artifact" ? "Artifact" : "Project File"}?
          </h2>
          <code>{pendingDeletion.label}</code>
          <p>This cannot be undone.</p>
          {deleteError ? <p className={styles.error}>{deleteError}</p> : null}
          <div className={styles.deleteDialogActions}>
            <button
              disabled={isDeleting}
              onClick={() => setPendingDeletion(null)}
              type="button"
            >
              Cancel
            </button>
            <button
              disabled={isDeleting}
              onClick={() => void deleteItem(pendingDeletion)}
              type="button"
            >
              {isDeleting ? "Deleting…" : "Delete"}
            </button>
          </div>
        </dialog>
      ) : null}
    </section>
  );
}
