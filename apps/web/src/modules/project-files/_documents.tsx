"use client";

import { useEffect, useState } from "react";
import { Button } from "@/shared/ui";
import styles from "./project-files.module.css";

export interface ProjectDocument {
  id: string;
  name: string;
  version: number;
  filePath: string;
  textPath: string;
  originalPath: string;
  sourceSha256: string;
  mediaType: string;
  pageCount: number | null;
  status: string;
  warnings: string[];
  converter: string;
}

export async function uploadProjectDocument(projectId: string, file: File) {
  if (file.size > 10_000_000)
    throw new Error("Documents must be 10 MB or smaller.");
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/files/documents?filename=${encodeURIComponent(file.name)}`,
    {
      method: "POST",
      headers: { "content-type": "application/octet-stream" },
      body: file,
    },
  );
  const body = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(
      typeof body.detail === "string" ? body.detail : "Document upload failed.",
    );
  return body as ProjectDocument;
}

export function DocumentPreview({
  projectId,
  documentId,
  initialPage = 1,
  initialMode = "original",
}: {
  projectId: string;
  documentId: string;
  initialPage?: number;
  initialMode?: "original" | "text";
}) {
  const base = `/api/projects/${encodeURIComponent(projectId)}/files/documents/${encodeURIComponent(documentId)}`;
  const [document, setDocument] = useState<ProjectDocument | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [page, setPage] = useState(initialPage);
  const [zoom, setZoom] = useState(100);
  const [mode, setMode] = useState<"original" | "text">(initialMode);
  const [imageError, setImageError] = useState(false);
  useEffect(() => {
    let active = true;
    fetch(base, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Document could not be loaded.");
        const value = (await response.json()) as ProjectDocument;
        if (active) {
          setDocument(value);
          if (!value.pageCount) setMode("text");
        }
      })
      .catch((error) => {
        if (active) setError(String(error));
      });
    return () => {
      active = false;
    };
  }, [base]);
  useEffect(() => {
    if (!document) return;
    let active = true;
    const path = document.pageCount
      ? document.textPath.replace(
          "text.md",
          `pages/${String(page).padStart(3, "0")}.md`,
        )
      : document.textPath;
    fetch(
      `/api/projects/${encodeURIComponent(projectId)}/files?path=${encodeURIComponent(path)}`,
      { cache: "no-store" },
    )
      .then(async (response) => {
        if (!response.ok)
          throw new Error("Extracted text could not be loaded.");
        return response.json();
      })
      .then((value) => {
        if (active) setText(value.content);
      })
      .catch((error) => {
        if (active) setError(String(error));
      });
    return () => {
      active = false;
    };
  }, [document, page, projectId]);
  if (error) return <p role="alert">{error}</p>;
  if (!document) return <p>Loading document…</p>;
  return (
    <section aria-label="Document viewer" className={styles.documentViewer}>
      <header>
        <h2>{document.name}</h2>
        <a href={`${base}/original`} download={document.name}>
          Download original
        </a>
      </header>
      {document.warnings.length ? (
        <details open={document.status !== "ready"}>
          <summary>Extraction warnings ({document.warnings.length})</summary>
          <ul>
            {document.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </details>
      ) : null}
      <div className={styles.documentToolbar}>
        {document.pageCount ? (
          <>
            <Button
              type="button"
              aria-pressed={mode === "original"}
              onClick={() => setMode("original")}
            >
              Original page
            </Button>
            <Button
              type="button"
              disabled={page === 1}
              onClick={() => {
                setImageError(false);
                setPage((p) => p - 1);
              }}
            >
              Previous page
            </Button>
            <label>
              Page{" "}
              <select
                aria-label="PDF page"
                value={page}
                onChange={(e) => {
                  setImageError(false);
                  setPage(Number(e.target.value));
                }}
              >
                {Array.from({ length: document.pageCount }, (_, i) => (
                  <option key={i + 1}>{i + 1}</option>
                ))}
              </select>{" "}
              of {document.pageCount}
            </label>
            <Button
              type="button"
              disabled={page === document.pageCount}
              onClick={() => {
                setImageError(false);
                setPage((p) => p + 1);
              }}
            >
              Next page
            </Button>
          </>
        ) : null}
        <Button
          type="button"
          aria-pressed={mode === "text"}
          onClick={() => setMode("text")}
        >
          Extracted Markdown
        </Button>
        {mode === "original" && document.pageCount ? (
          <label>
            Zoom{" "}
            <select
              aria-label="Document zoom"
              value={zoom}
              onChange={(e) => setZoom(Number(e.target.value))}
            >
              {[75, 100, 125, 150, 200].map((v) => (
                <option key={v} value={v}>
                  {v}%
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>
      <div className={styles.documentStage}>
        {mode === "original" && document.pageCount ? (
          imageError ? (
            <p role="alert">
              This page could not be rendered. Download the original or retry by
              changing pages.
            </p>
          ) : (
            // The authenticated image endpoint renders the retained original PDF on demand.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={page}
              src={`${base}/pages/${page}/image`}
              alt={`${document.name}, page ${page}`}
              onError={() => setImageError(true)}
              style={{ width: `${zoom}%`, maxWidth: "none" }}
            />
          )
        ) : (
          <pre>
            {text ||
              "No text extracted. Inspect the original page; this document may need OCR."}
          </pre>
        )}
      </div>
      <details>
        <summary>Source and extraction details</summary>
        <p>{document.textPath}</p>
        <p>Source SHA-256: {document.sourceSha256}</p>
        <p>
          {document.converter} · {document.status} · Version {document.version}
        </p>
      </details>
    </section>
  );
}
