"use client";

import {
  AppBridge,
  PostMessageTransport,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import { useEffect, useRef, useState } from "react";

import type { ArtifactDocument } from "@/contracts";

import styles from "./artifact-view-host.module.css";

function toolError(message: string) {
  return { content: [{ text: message, type: "text" as const }], isError: true };
}

interface AppState {
  availability: "available" | "loading" | "unavailable";
  error: string | null;
  key: string;
}

export function ArtifactApp({
  artifactId,
  document,
  projectId,
}: {
  artifactId: string;
  document: ArtifactDocument;
  projectId: string;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [appState, setAppState] = useState<AppState>({
    availability: "loading",
    error: null,
    key: "",
  });
  const appUrl = `/api/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}/app`;
  const availability =
    appState.key === appUrl ? appState.availability : "loading";
  const error = appState.key === appUrl ? appState.error : null;

  useEffect(() => {
    let active = true;
    fetch(appUrl, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        if (active) {
          setAppState({ availability: "available", error: null, key: appUrl });
        }
      })
      .catch(() => {
        if (active) {
          setAppState({
            availability: "unavailable",
            error: null,
            key: appUrl,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [appUrl]);

  useEffect(() => {
    if (availability !== "available") return;
    const iframe = frame.current;
    if (!iframe?.contentWindow) return;
    let disposed = false;
    const bridge = new AppBridge(
      null,
      { name: "Agent Hub", version: "0.0.0" },
      { sandbox: { csp: {}, permissions: {} }, serverTools: {} },
      { hostContext: { platform: "web" } },
    );

    bridge.oncalltool = async () =>
      toolError("This App does not expose any host-approved tools.");
    bridge.oninitialized = () => {
      void bridge
        .sendToolInput({ arguments: { document } })
        .then(() =>
          bridge.sendToolResult({ content: [], structuredContent: document }),
        )
        .catch(() => {
          if (!disposed) {
            setAppState({
              availability: "available",
              error: "The Artifact App could not be initialized.",
              key: appUrl,
            });
          }
        });
    };

    void bridge
      .connect(
        new PostMessageTransport(iframe.contentWindow, iframe.contentWindow),
      )
      .then(() => {
        if (!disposed) iframe.src = appUrl;
      })
      .catch(() => {
        if (!disposed) {
          setAppState({
            availability: "available",
            error: "The Artifact App could not be initialized.",
            key: appUrl,
          });
        }
      });
    return () => {
      disposed = true;
      void bridge.teardownResource({}).catch(() => {});
      void bridge.close();
    };
  }, [appUrl, availability, document]);

  return (
    <section aria-label="Artifact App" className={styles.app}>
      {error ? <p className={styles.error}>{error}</p> : null}
      {availability === "loading" ? (
        <p>Loading compatible Artifact App…</p>
      ) : null}
      {availability === "unavailable" ? (
        <p>
          A compatible Artifact App is unavailable. The generic safe view is
          shown below.
        </p>
      ) : null}
      {availability === "available" ? (
        <iframe
          className={styles.appFrame}
          ref={frame}
          referrerPolicy="no-referrer"
          sandbox="allow-scripts"
          src={appUrl}
          title="Artifact App"
        />
      ) : null}
    </section>
  );
}
