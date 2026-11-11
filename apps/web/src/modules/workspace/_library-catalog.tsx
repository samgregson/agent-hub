"use client";

import { useEffect, useState } from "react";

import type { ArtifactCatalog, ProjectFileCatalog } from "@/contracts";
import { Collection, CollectionItem, Menu, MenuItem } from "@/shared/ui";

import { DocumentUpload, type ProjectDocument } from "@/modules/project-files";

import styles from "./workspace.module.css";

type LibraryItem =
  | {
      id: string;
      kind: "document";
      label: string;
      path: string;
      version: number;
    }
  | { id: string; kind: "artifact"; label: string; version: number }
  | {
      id: string;
      kind: "dataset";
      label: string;
      path: string;
      version: number;
    }
  | { kind: "projectFile"; label: string; path: string; version: number };

interface DatasetSummary {
  id: string;
  name: string;
  filePath: string;
  version: number;
}

type PendingDeletion = LibraryItem | null;

const libraryKindLabels = {
  document: "Document",
  artifact: "Artifact",
  dataset: "Dataset",
  projectFile: "Project File",
} as const;

interface LibraryCatalogResult {
  error: string | null;
  items: LibraryItem[] | null;
  projectId: string;
}

function combineLibraryItems(
  artifacts: ArtifactCatalog,
  files: ProjectFileCatalog,
  datasets: DatasetSummary[],
  documents: ProjectDocument[],
): LibraryItem[] {
  return [
    ...documents.map((d) => ({
      id: d.id,
      kind: "document" as const,
      label: d.name,
      path: d.filePath,
      version: d.version,
    })),
    ...artifacts.artifacts.map((artifact) => ({
      id: artifact.id,
      kind: "artifact" as const,
      label: artifact.title,
      version: artifact.documentVersion,
    })),
    ...datasets.map((dataset) => ({
      id: dataset.id,
      kind: "dataset" as const,
      label: dataset.name,
      path: dataset.filePath,
      version: dataset.version,
    })),
    ...files.files
      .filter(
        (file) =>
          !file.path.startsWith("/project/.datasets/") &&
          !file.path.startsWith("/project/.documents/"),
      )
      .map((file) => ({
        kind: "projectFile" as const,
        label: file.path,
        path: file.path,
        version: file.version,
      })),
  ].sort((left, right) => left.label.localeCompare(right.label));
}

export function LibraryCatalog({
  onOpenArtifact,
  onOpenProjectFile,
  projectId,
  refreshKey,
}: {
  onOpenArtifact: (artifactId: string) => void;
  onOpenProjectFile: (path: string) => void;
  projectId: string;
  refreshKey: number;
}) {
  const [uploadRevision, setUploadRevision] = useState(0);
  const [result, setResult] = useState<LibraryCatalogResult>({
    error: null,
    items: null,
    projectId: "",
  });
  const [pendingDeletion, setPendingDeletion] = useState<PendingDeletion>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [addingDataset, setAddingDataset] = useState(false);
  const [datasetName, setDatasetName] = useState("");
  const [datasetRecords, setDatasetRecords] = useState("[]");
  const [createError, setCreateError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const items = result.projectId === projectId ? result.items : null;
  const error = result.projectId === projectId ? result.error : null;

  async function uploadFiles(files: FileList) {
    setUploading(true);
    setUploadError(null);
    const errors: string[] = [];
    for (const file of Array.from(files)) {
      try {
        const bytes = await file.arrayBuffer();
        const content = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
        const response = await fetch(
          `/api/projects/${encodeURIComponent(projectId)}/files`,
          {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ path: `/project/${file.name}`, content }),
          },
        );
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(
            typeof body.detail === "string" ? body.detail : "Upload failed",
          );
        }
        const saved = (await response.json()) as {
          path: string;
          version: number;
        };
        setResult((current) =>
          current.projectId !== projectId || current.items === null
            ? current
            : {
                ...current,
                items: [
                  ...current.items,
                  {
                    kind: "projectFile" as const,
                    label: saved.path,
                    path: saved.path,
                    version: saved.version,
                  },
                ].sort((a, b) => a.label.localeCompare(b.label)),
              },
        );
      } catch (error) {
        errors.push(
          `${file.name}: ${error instanceof Error ? error.message : "Upload failed"}`,
        );
      }
    }
    if (errors.length) setUploadError(errors.join("; "));
    setUploading(false);
  }

  async function createDataset() {
    let records: unknown;
    try {
      records = JSON.parse(datasetRecords);
      if (!Array.isArray(records)) throw new Error();
    } catch {
      setCreateError("Records must be a JSON array.");
      return;
    }
    setIsCreating(true);
    setCreateError(null);
    try {
      const response = await fetch(
        `/api/projects/${encodeURIComponent(projectId)}/datasets`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ name: datasetName, records }),
        },
      );
      if (!response.ok) throw new Error();
      const created = (await response.json()) as DatasetSummary;
      setResult((current) =>
        current.projectId !== projectId || current.items === null
          ? current
          : {
              ...current,
              items: [
                ...current.items,
                {
                  id: created.id,
                  kind: "dataset" as const,
                  label: created.name,
                  path: created.filePath,
                  version: created.version,
                },
              ].sort((left, right) => left.label.localeCompare(right.label)),
            },
      );
      setAddingDataset(false);
      setDatasetName("");
      setDatasetRecords("[]");
      onOpenProjectFile(created.filePath);
    } catch {
      setCreateError("Dataset could not be saved.");
    } finally {
      setIsCreating(false);
    }
  }

  async function deleteItem(item: LibraryItem) {
    setIsDeleting(true);
    setDeleteError(null);
    try {
      const encodedProjectId = encodeURIComponent(projectId);
      const response =
        item.kind === "document"
          ? await fetch(
              `/api/projects/${encodedProjectId}/files/documents/${encodeURIComponent(item.id)}`,
              { method: "DELETE" },
            )
          : item.kind === "artifact"
            ? await fetch(
                `/api/projects/${encodedProjectId}/artifacts/${encodeURIComponent(item.id)}`,
                { method: "DELETE" },
              )
            : item.kind === "dataset"
              ? await fetch(
                  `/api/projects/${encodedProjectId}/datasets/${encodeURIComponent(item.id)}`,
                  {
                    method: "DELETE",
                  },
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
      fetch(`/api/projects/${encodedProjectId}/datasets`, {
        cache: "no-store",
      }),
      fetch(`/api/projects/${encodedProjectId}/files/documents`, {
        cache: "no-store",
      }),
    ])
      .then(
        async ([
          artifactResponse,
          fileResponse,
          datasetResponse,
          documentResponse,
        ]) => {
          if (
            !artifactResponse.ok ||
            !fileResponse.ok ||
            !datasetResponse.ok ||
            !documentResponse.ok
          ) {
            throw new Error("Library catalog unavailable");
          }
          return combineLibraryItems(
            (await artifactResponse.json()) as ArtifactCatalog,
            (await fileResponse.json()) as ProjectFileCatalog,
            (await datasetResponse.json()) as DatasetSummary[],
            (await documentResponse.json()) as ProjectDocument[],
          );
        },
      )
      .then((loaded) => {
        if (active) setResult({ error: null, items: loaded, projectId });
      })
      .catch(() => {
        if (active) {
          setResult({
            error: "Library items are temporarily unavailable.",
            items: null,
            projectId,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [projectId, refreshKey, uploadRevision]);

  return (
    <section aria-label="Library items">
      <label>
        Upload Project files (UTF-8 text)
        <input
          type="file"
          multiple
          disabled={uploading}
          onChange={(event) => {
            if (event.target.files?.length)
              void uploadFiles(event.target.files);
            event.target.value = "";
          }}
        />
      </label>
      {uploading ? <p>Uploading…</p> : null}
      {uploadError ? (
        <p className={styles.error} role="alert">
          {uploadError}
        </p>
      ) : null}
      <DocumentUpload
        key={projectId}
        projectId={projectId}
        onUploaded={(document) => {
          setUploadRevision((n) => n + 1);
          onOpenProjectFile(document.filePath);
        }}
      />
      <button
        className={styles.newThread}
        onClick={() => setAddingDataset((current) => !current)}
        type="button"
      >
        + New Dataset
      </button>
      {addingDataset ? (
        <form
          className={styles.datasetForm}
          onSubmit={(event) => {
            event.preventDefault();
            void createDataset();
          }}
        >
          <label>
            Name
            <input
              onChange={(event) => setDatasetName(event.target.value)}
              value={datasetName}
            />
          </label>
          <label>
            Records (JSON array)
            <textarea
              onChange={(event) => setDatasetRecords(event.target.value)}
              rows={5}
              value={datasetRecords}
            />
          </label>
          {createError ? (
            <p className={styles.error} role="alert">
              {createError}
            </p>
          ) : null}
          <div className={styles.datasetFormActions}>
            <button disabled={isCreating} type="submit">
              {isCreating ? "Saving…" : "Save Dataset"}
            </button>
          </div>
        </form>
      ) : null}
      {error ? <p className={styles.error}>{error}</p> : null}
      {!items && !error ? <p>Loading Library…</p> : null}
      <Collection>
        {items?.map((item) => (
          <CollectionItem
            actions={
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
            }
            details={`${libraryKindLabels[item.kind]} · Version ${item.version}`}
            key={item.kind === "artifact" ? item.id : item.path}
            openLabel={item.label}
            onOpen={() =>
              item.kind === "artifact"
                ? onOpenArtifact(item.id)
                : onOpenProjectFile(item.path)
            }
            title={item.label}
          />
        ))}
      </Collection>
      {items?.length === 0 ? <p>No Library items yet.</p> : null}
      {pendingDeletion ? (
        <dialog
          aria-label="Confirm deletion"
          className={styles.deleteDialog}
          open
        >
          <p className={styles.deleteDialogEyebrow}>Permanent removal</p>
          <h2>
            Delete this{" "}
            {pendingDeletion.kind === "artifact"
              ? "Artifact"
              : pendingDeletion.kind === "dataset"
                ? "Dataset"
                : "Project File"}
            ?
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
