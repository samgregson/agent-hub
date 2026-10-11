"use client";

import { useState } from "react";

import type { WorkflowDefinition } from "./_overview";
import styles from "./workflow-overview.module.css";

type EditableGraph = WorkflowDefinition["graph"];

export function WorkflowDefinitionEditor({
  definition,
  onCancel,
  onSaved,
  projectId,
}: {
  definition: WorkflowDefinition;
  onCancel: () => void;
  onSaved: (definition: WorkflowDefinition) => void;
  projectId: string;
}) {
  const [name, setName] = useState(definition.name);
  const [graph, setGraph] = useState<EditableGraph>(() =>
    structuredClone(definition.graph),
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function updateEdge(
    index: number,
    patch: Partial<EditableGraph["edges"][number]>,
  ) {
    setGraph((current) => ({
      ...current,
      edges: current.edges.map((edge, edgeIndex) =>
        edgeIndex === index ? { ...edge, ...patch } : edge,
      ),
    }));
  }

  function updateOutput(
    index: number,
    patch: Partial<EditableGraph["outputs"][number]>,
  ) {
    setGraph((current) => ({
      ...current,
      outputs: current.outputs.map((output, outputIndex) =>
        outputIndex === index ? { ...output, ...patch } : output,
      ),
    }));
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(definition.id)}`,
        {
          method: "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            name,
            graph,
            expectedVersion: definition.version,
          }),
        },
      );
      if (!response.ok) {
        const body = (await response.json()) as { detail?: string };
        throw new Error(body.detail ?? "Workflow could not be saved.");
      }
      onSaved((await response.json()) as WorkflowDefinition);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Workflow could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-label="Edit Workflow Definition" className={styles.editor}>
      <div className={styles.sectionHeading}>
        <div>
          <h2>Edit Workflow Definition</h2>
          <p>
            Change connections and final outputs. Runs already captured keep
            their original Definition.
          </p>
        </div>
        <button onClick={onCancel} type="button">
          Cancel
        </button>
      </div>
      <label className={styles.editorField}>
        <span>Workflow name</span>
        <input onChange={(event) => setName(event.target.value)} value={name} />
      </label>

      <section aria-label="Workflow connections" className={styles.editorGroup}>
        <div className={styles.sectionHeading}>
          <h3>Connections</h3>
          <button
            onClick={() =>
              setGraph((current) => ({
                ...current,
                edges: [
                  ...current.edges,
                  {
                    sourceNode: current.nodes[0]?.id ?? "",
                    sourcePort: "",
                    targetNode: current.nodes.at(-1)?.id ?? "",
                    targetPort: "",
                  },
                ],
              }))
            }
            type="button"
          >
            Add connection
          </button>
        </div>
        {graph.edges.map((edge, index) => (
          <div className={styles.editorRow} key={`edge-${index}`}>
            <label>
              <span>From node</span>
              <select
                onChange={(event) =>
                  updateEdge(index, { sourceNode: event.target.value })
                }
                value={edge.sourceNode}
              >
                {graph.nodes.map((node) => (
                  <option key={node.id} value={node.id}>
                    {node.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Output port</span>
              <input
                onChange={(event) =>
                  updateEdge(index, { sourcePort: event.target.value })
                }
                value={edge.sourcePort}
              />
            </label>
            <span aria-hidden="true" className={styles.editorArrow} />
            <label>
              <span>To node</span>
              <select
                onChange={(event) =>
                  updateEdge(index, { targetNode: event.target.value })
                }
                value={edge.targetNode}
              >
                {graph.nodes.map((node) => (
                  <option key={node.id} value={node.id}>
                    {node.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Input port</span>
              <input
                onChange={(event) =>
                  updateEdge(index, { targetPort: event.target.value })
                }
                value={edge.targetPort}
              />
            </label>
            <button
              aria-label={`Remove connection ${index + 1}`}
              onClick={() =>
                setGraph((current) => ({
                  ...current,
                  edges: current.edges.filter(
                    (_, edgeIndex) => edgeIndex !== index,
                  ),
                }))
              }
              type="button"
            >
              Remove
            </button>
          </div>
        ))}
      </section>

      <section
        aria-label="Workflow outputs editor"
        className={styles.editorGroup}
      >
        <div className={styles.sectionHeading}>
          <h3>Final outputs</h3>
          <button
            onClick={() =>
              setGraph((current) => ({
                ...current,
                outputs: [
                  ...current.outputs,
                  {
                    name: `output${current.outputs.length + 1}`,
                    node: current.nodes.at(-1)?.id ?? "",
                    port: "result",
                  },
                ],
              }))
            }
            type="button"
          >
            Add output
          </button>
        </div>
        {graph.outputs.map((output, index) => (
          <div className={styles.editorRow} key={`output-${index}`}>
            <label>
              <span>Name</span>
              <input
                onChange={(event) =>
                  updateOutput(index, { name: event.target.value })
                }
                value={output.name}
              />
            </label>
            <label>
              <span>From node</span>
              <select
                onChange={(event) =>
                  updateOutput(index, { node: event.target.value })
                }
                value={output.node}
              >
                {graph.nodes.map((node) => (
                  <option key={node.id} value={node.id}>
                    {node.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Output port</span>
              <input
                onChange={(event) =>
                  updateOutput(index, { port: event.target.value })
                }
                value={output.port}
              />
            </label>
            <button
              aria-label={`Remove final output ${index + 1}`}
              disabled={graph.outputs.length === 1}
              onClick={() =>
                setGraph((current) => ({
                  ...current,
                  outputs: current.outputs.filter(
                    (_, outputIndex) => outputIndex !== index,
                  ),
                }))
              }
              type="button"
            >
              Remove
            </button>
          </div>
        ))}
      </section>

      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      <div className={styles.editorActions}>
        <button
          disabled={saving || !name.trim()}
          onClick={() => void save()}
          type="button"
        >
          {saving ? "Saving…" : "Save new Definition version"}
        </button>
      </div>
    </section>
  );
}
