"use client";

import { useEffect, useState } from "react";

import styles from "./plugin-gateway.module.css";
import {
  listPluginSelections,
  setPluginEnabled,
  type PluginSelection,
} from "./_plugins";

interface PluginCatalogProps {
  projectId: string;
}

export function PluginCatalog({ projectId }: PluginCatalogProps) {
  const [selections, setSelections] = useState<PluginSelection[]>([]);
  const [changingPluginId, setChangingPluginId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listPluginSelections(projectId)
      .then((loaded) => {
        if (active) {
          setError(null);
          setSelections(loaded);
        }
      })
      .catch(() => {
        if (active) setError("Plugins are temporarily unavailable.");
      });
    return () => {
      active = false;
    };
  }, [projectId]);

  async function toggleSelection(selection: PluginSelection) {
    setChangingPluginId(selection.id);
    setError(null);
    try {
      await setPluginEnabled(projectId, selection.id, !selection.enabled);
      setSelections((current) =>
        current.map((item) =>
          item.id === selection.id ? { ...item, enabled: !item.enabled } : item,
        ),
      );
    } catch {
      setError("The Plugin selection could not be updated.");
    } finally {
      setChangingPluginId(null);
    }
  }

  if (error) return <p className={styles.error}>{error}</p>;
  if (!selections.length)
    return <p className={styles.empty}>No reviewed Plugins are available.</p>;

  return (
    <div className={styles.catalog}>
      {selections.map((selection) => (
        <article className={styles.plugin} key={selection.id}>
          <div>
            <strong>{selection.name}</strong>
            <p>Version {selection.version}</p>
            <p>{selection.tools.map((tool) => tool.name).join(", ")}</p>
          </div>
          <button
            aria-pressed={selection.enabled}
            className={styles.toggle}
            disabled={changingPluginId === selection.id}
            onClick={() => void toggleSelection(selection)}
            type="button"
          >
            {changingPluginId === selection.id
              ? "Updating…"
              : selection.enabled
                ? "Enabled"
                : "Enable"}
          </button>
        </article>
      ))}
    </div>
  );
}
