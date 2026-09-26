"use client";

import { useEffect, useState } from "react";

import { Button, Collection, CollectionItem } from "@/shared/ui";
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

  if (error) return <p role="alert">Plugins are temporarily unavailable.</p>;
  if (!selections.length) return <p>No reviewed Plugins are available.</p>;

  return (
    <Collection>
      {selections.map((selection) => (
        <CollectionItem
          actions={
            <Button
              aria-pressed={selection.enabled}
              disabled={changingPluginId === selection.id}
              onClick={() => void toggleSelection(selection)}
              variant={selection.enabled ? "primary" : "secondary"}
            >
              {changingPluginId === selection.id
                ? "Updating…"
                : selection.enabled
                  ? "Enabled"
                  : "Enable"}
            </Button>
          }
          details={`Version ${selection.version} · ${selection.tools.map((tool) => tool.name).join(", ")}`}
          key={selection.id}
          title={selection.name}
        />
      ))}
    </Collection>
  );
}
