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

type McpToolResult = {
  content: { type: "text"; text: string }[];
  structuredContent: Record<string, unknown>;
};

interface AppState {
  availability: "available" | "loading" | "unavailable";
  message: string | null;
  key: string;
}

export function McpAppFrame({
  appUrl,
  toolInput,
  toolResult,
  title,
}: {
  appUrl: string;
  toolInput: Record<string, unknown>;
  toolResult: McpToolResult;
  title: string;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const payload = useRef({ toolInput, toolResult });
  payload.current = { toolInput, toolResult };
  const [attempt, setAttempt] = useState(0);
  const [appState, setAppState] = useState<AppState>({
    availability: "loading",
    message: null,
    key: "",
  });
  const availability =
    appState.key === appUrl ? appState.availability : "loading";
  const message = appState.key === appUrl ? appState.message : null;

  useEffect(() => {
    let active = true;
    setAppState({ availability: "loading", message: null, key: appUrl });
    fetch(appUrl, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) {
          if (response.status === 404 || response.status === 422) {
            throw new Error("unavailable");
          }
          throw new Error("load_failed");
        }
        if (active) {
          setAppState({
            availability: "available",
            message: null,
            key: appUrl,
          });
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setAppState({
            availability: "unavailable",
            message:
              error instanceof Error && error.message === "unavailable"
                ? "This saved result has no interactive App for its captured version. Its data is still available in the surrounding view."
                : "The interactive App could not be loaded. Its data is still available in the surrounding view.",
            key: appUrl,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [appUrl, attempt]);

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
      toolError("This preview cannot run tools or change the saved result.");
    bridge.oninitialized = () => {
      const current = payload.current;
      void bridge
        .sendToolInput({ arguments: current.toolInput })
        .then(() => bridge.sendToolResult(current.toolResult))
        .catch(() => {
          if (!disposed) {
            setAppState({
              availability: "unavailable",
              message:
                "The interactive App could not receive this saved result. Its inputs and output are still available.",
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
            availability: "unavailable",
            message:
              "The interactive App could not be initialized. Its inputs and output are still available.",
            key: appUrl,
          });
        }
      });
    return () => {
      disposed = true;
      void bridge.teardownResource({}).catch(() => {});
      void bridge.close();
    };
  }, [appUrl, availability]);

  return (
    <section aria-label={title} className={styles.app}>
      {availability === "loading" ? <p>Loading interactive App…</p> : null}
      {availability === "unavailable" ? (
        <div className={styles.appUnavailable} role="status">
          <p>{message}</p>
          <button
            onClick={() => setAttempt((value) => value + 1)}
            type="button"
          >
            Retry
          </button>
        </div>
      ) : null}
      {availability === "available" ? (
        <iframe
          className={styles.appFrame}
          ref={frame}
          referrerPolicy="no-referrer"
          sandbox="allow-scripts"
          title={title}
        />
      ) : null}
    </section>
  );
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
  const appUrl = `/api/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}/app`;
  return (
    <McpAppFrame
      appUrl={appUrl}
      title="Artifact App"
      toolInput={{ document }}
      toolResult={{
        content: [],
        structuredContent: document as unknown as Record<string, unknown>,
      }}
    />
  );
}
