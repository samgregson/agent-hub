"use client";

import { useEffect, useState } from "react";

import type { WorkflowDefinition } from "./_overview";
import styles from "./workflow-overview.module.css";

type EditableGraph = WorkflowDefinition["graph"];

type AddableNode = {
  id: string;
  label: string;
  kind: "dataset" | "file" | "python" | "mcp";
  version: number | string;
  toolName?: string;
  inputPorts: string[];
  repeatSafe: boolean;
};

type EditorCatalog = {
  error: string | null;
  warning: string | null;
  items: AddableNode[] | null;
};

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
  const [catalog, setCatalog] = useState<EditorCatalog>({
    error: null,
    warning: null,
    items: null,
  });
  const [selectedAddableNode, setSelectedAddableNode] = useState("");
  const [newNodeShape, setNewNodeShape] = useState<"single" | "map">("single");

  useEffect(() => {
    let active = true;
    const root = `/api/projects/${encodeURIComponent(projectId)}`;
    void Promise.all([
      fetch(`${root}/datasets`, { cache: "no-store" }),
      fetch(`${root}/files/index`, { cache: "no-store" }),
      fetch(`${root}/transforms`, { cache: "no-store" }),
      fetch(`${root}/plugins`, { cache: "no-store" }),
    ])
      .then(async (responses) => {
        if (responses.some((response) => !response.ok)) {
          throw new Error("Library and Operation items could not be loaded.");
        }
        const [datasets, files, functions, plugins] = (await Promise.all(
          responses.map((response) => response.json()),
        )) as [
          Array<{ id: string; name: string; version: number }>,
          { files: Array<{ path: string; version: number }> },
          Array<{
            id: string;
            name: string;
            revision: number;
            inputSchema: { properties?: Record<string, unknown> };
          }>,
          Array<{
            id: string;
            name: string;
            version: string;
            enabled: boolean;
            tools: Array<{ name: string }>;
          }>,
        ];
        const baseItems: AddableNode[] = [
          ...datasets.map((dataset) => ({
            id: dataset.id,
            label: `Dataset · ${dataset.name}`,
            kind: "dataset" as const,
            version: dataset.version,
            inputPorts: [],
            repeatSafe: false,
          })),
          ...files.files
            .filter((file) => !file.path.startsWith("/project/.datasets/"))
            .map((file) => ({
              id: file.path,
              label: `Project File · ${file.path}`,
              kind: "file" as const,
              version: file.version,
              inputPorts: [],
              repeatSafe: false,
            })),
          ...functions.map((definition) => ({
            id: definition.id,
            label: `Function · ${definition.name}`,
            kind: "python" as const,
            version: definition.revision,
            inputPorts: Object.keys(definition.inputSchema.properties ?? {}),
            repeatSafe: false,
          })),
        ];
        const enabledPlugins = plugins.filter((plugin) => plugin.enabled);
        const contractResults = await Promise.all(
          enabledPlugins.map(async (plugin) => {
            try {
              const response = await fetch(
                `${root}/plugins/${encodeURIComponent(plugin.id)}/tools`,
                { cache: "no-store" },
              );
              if (!response.ok) return { plugin, tools: null };
              return {
                plugin,
                tools: (await response.json()) as Array<{
                  name: string;
                  version: string;
                  repeatSafe: boolean;
                  inputSchema: { properties?: Record<string, unknown> };
                }>,
              };
            } catch {
              return { plugin, tools: null };
            }
          }),
        );
        const mcpItems: AddableNode[] = contractResults.flatMap(
          ({ plugin, tools }) =>
            (tools ?? []).map((tool) => ({
              id: plugin.id,
              label: `MCP · ${plugin.name} / ${tool.name}`,
              kind: "mcp" as const,
              version: tool.version,
              toolName: tool.name,
              inputPorts: Object.keys(tool.inputSchema.properties ?? {}),
              repeatSafe: tool.repeatSafe,
            })),
        );
        const items: AddableNode[] = [...baseItems, ...mcpItems];
        const expectedMcpTools = enabledPlugins.reduce(
          (count, plugin) => count + plugin.tools.length,
          0,
        );
        const unavailableMcpTools =
          contractResults.some(({ tools }) => tools === null) ||
          mcpItems.length < expectedMcpTools;
        if (active) {
          setCatalog({
            error: null,
            warning: unavailableMcpTools
              ? "Some MCP tool contracts are unavailable and were not added to the editor."
              : null,
            items,
          });
          setSelectedAddableNode(items[0]?.label ?? "");
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setCatalog({
            error:
              cause instanceof Error
                ? cause.message
                : "Library and Operation items could not be loaded.",
            items: [],
            warning: null,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [projectId]);

  const selectedAddableItem = catalog.items?.find(
    (item) => item.label === selectedAddableNode,
  );

  function outputPortFor(nodeId: string) {
    const node = graph.nodes.find((candidate) => candidate.id === nodeId);
    if (!node) return "result";
    if (node.kind === "dataset") return "records";
    if (node.kind === "file") return "content";
    return "result";
  }

  function inputPortFor(nodeId: string) {
    return inputPortsFor(nodeId)[0] ?? "";
  }

  function inputPortsFor(nodeId: string) {
    const node = graph.nodes.find((candidate) => candidate.id === nodeId);
    if (!node || node.kind === "dataset" || node.kind === "file") return [];
    const item = catalog.items?.find(
      (candidate) =>
        candidate.id === node.refId &&
        candidate.kind === node.kind &&
        candidate.toolName === node.toolName,
    );
    if (node.shape === "map")
      return node.kind === "mcp"
        ? [
            "items",
            ...(item?.inputPorts ?? []).filter((port) => port !== "items"),
          ]
        : ["items"];
    return item?.inputPorts ?? [];
  }

  function addNode() {
    if (!selectedAddableItem) return;
    const item = selectedAddableItem;
    const prefix =
      item.kind === "dataset" || item.kind === "file" ? "input" : "call";
    let sequence = graph.nodes.length + 1;
    let id = `${prefix}-${sequence}`;
    while (graph.nodes.some((node) => node.id === id)) {
      sequence += 1;
      id = `${prefix}-${sequence}`;
    }
    const node = {
      id,
      kind: item.kind,
      refId: item.id,
      version: item.version,
      shape:
        (item.kind === "python" || item.kind === "mcp") &&
        newNodeShape === "map" &&
        (item.kind === "mcp" ? item.repeatSafe : item.inputPorts.length === 1)
          ? "map"
          : "single",
      ...(item.toolName ? { toolName: item.toolName } : {}),
    };
    setGraph((current) => ({
      ...current,
      nodes: [...current.nodes, node],
      outputs:
        current.outputs.length > 0
          ? current.outputs
          : [
              {
                name: "result",
                node: id,
                port:
                  item.kind === "dataset"
                    ? "records"
                    : item.kind === "file"
                      ? "content"
                      : "result",
              },
            ],
    }));
  }

  function removeNode(id: string) {
    setGraph((current) => {
      const nodes = current.nodes.filter((node) => node.id !== id);
      const outputs = current.outputs.filter((output) => output.node !== id);
      if (nodes.length === 0 || outputs.length === 0) return current;
      return {
        ...current,
        nodes,
        edges: current.edges.filter(
          (edge) => edge.sourceNode !== id && edge.targetNode !== id,
        ),
        outputs,
      };
    });
  }

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
      const isNew = !definition.id;
      const base = `/api/projects/${encodeURIComponent(projectId)}/workflows`;
      const response = await fetch(
        isNew ? base : `${base}/${encodeURIComponent(definition.id)}`,
        {
          method: isNew ? "POST" : "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            name,
            graph,
            ...(!isNew ? { expectedVersion: definition.version } : {}),
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
            Add or remove nodes, connect named ports, and choose final outputs.
            Existing Runs keep their captured Definition.
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

      <section aria-label="Workflow nodes" className={styles.editorGroup}>
        <div className={styles.sectionHeading}>
          <h3>Nodes</h3>
        </div>
        <div className={styles.nodeEditorList}>
          {graph.nodes.map((node) => (
            <article className={styles.nodeEditorCard} key={node.id}>
              <div>
                <strong>{node.id}</strong>
                <span>
                  {node.kind === "mcp" ? "MCP tool" : node.kind} · {node.refId}
                  {node.toolName ? ` / ${node.toolName}` : ""}
                </span>
              </div>
              <button
                aria-label={`Remove node ${node.id}`}
                disabled={
                  graph.nodes.length <= 1 ||
                  (graph.outputs.length === 1 &&
                    graph.outputs[0]?.node === node.id)
                }
                onClick={() => removeNode(node.id)}
                type="button"
              >
                Remove node
              </button>
            </article>
          ))}
        </div>
        <p>
          To remove a node that provides the only final output, first point an
          output at another node.
        </p>
        {catalog.warning ? (
          <p className={styles.notice} role="status">
            {catalog.warning}
          </p>
        ) : null}
        {catalog.error ? (
          <p className={styles.error} role="alert">
            {catalog.error}
          </p>
        ) : catalog.items === null ? (
          <p role="status">Loading Library and Operations…</p>
        ) : catalog.items.length === 0 ? (
          <p>No eligible Library items or call definitions are available.</p>
        ) : (
          <div className={styles.addNode}>
            <label>
              <span>Library item or call</span>
              <select
                onChange={(event) => setSelectedAddableNode(event.target.value)}
                value={selectedAddableNode}
              >
                {catalog.items.map((item) => (
                  <option key={`${item.kind}-${item.label}`} value={item.label}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            {selectedAddableItem?.kind === "python" ||
            selectedAddableItem?.kind === "mcp" ? (
              <label>
                <span>Call shape</span>
                <select
                  onChange={(event) =>
                    setNewNodeShape(event.target.value as "single" | "map")
                  }
                  value={newNodeShape}
                >
                  <option value="single">Single item</option>
                  <option
                    disabled={
                      selectedAddableItem.kind === "python"
                        ? selectedAddableItem.inputPorts.length !== 1
                        : !selectedAddableItem.repeatSafe
                    }
                    value="map"
                  >
                    Map over a collection
                  </option>
                </select>
              </label>
            ) : null}
            <button onClick={addNode} type="button">
              Add node
            </button>
          </div>
        )}
      </section>

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
                    sourcePort: outputPortFor(current.nodes[0]?.id ?? ""),
                    targetNode: current.nodes.at(-1)?.id ?? "",
                    targetPort: inputPortFor(current.nodes.at(-1)?.id ?? ""),
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
                  updateEdge(index, {
                    sourceNode: event.target.value,
                    sourcePort: outputPortFor(event.target.value),
                  })
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
                readOnly
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
                  updateEdge(index, {
                    targetNode: event.target.value,
                    targetPort: inputPortFor(event.target.value),
                  })
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
                list={`workflow-input-ports-${index}`}
                onChange={(event) =>
                  updateEdge(index, { targetPort: event.target.value })
                }
                value={edge.targetPort}
              />
              <datalist id={`workflow-input-ports-${index}`}>
                {inputPortsFor(edge.targetNode).map((port) => (
                  <option key={port} value={port} />
                ))}
              </datalist>
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
                    port: outputPortFor(current.nodes.at(-1)?.id ?? ""),
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
                  updateOutput(index, {
                    node: event.target.value,
                    port: outputPortFor(event.target.value),
                  })
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
                readOnly
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

      <section aria-label="Draft Workflow graph" className={styles.draftGraph}>
        <h3>Draft graph</h3>
        <div className={styles.draftGraphNodes}>
          {graph.nodes.map((node) => (
            <article key={node.id}>
              <strong>{node.id}</strong>
              <span>
                {node.kind === "mcp" ? "MCP tool" : node.kind} · {node.refId}
                {node.toolName ? ` / ${node.toolName}` : ""}
                {node.shape === "map" ? " · Map" : ""}
              </span>
            </article>
          ))}
        </div>
        <ul aria-label="Draft dependencies">
          {graph.edges.map((edge, index) => (
            <li key={`draft-edge-${index}`}>
              <span>{edge.sourceNode}</span>
              <code>{edge.sourcePort}</code>
              <span aria-hidden="true">→</span>
              <span>{edge.targetNode}</span>
              <code>{edge.targetPort}</code>
            </li>
          ))}
        </ul>
        <ul aria-label="Draft final outputs">
          {graph.outputs.map((output, index) => (
            <li key={`draft-output-${index}`}>
              <strong>{output.name}</strong>
              <span>
                {output.node} · {output.port}
              </span>
            </li>
          ))}
        </ul>
      </section>

      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      <div className={styles.editorActions}>
        <button
          disabled={
            saving ||
            !name.trim() ||
            !graph.nodes.length ||
            !graph.outputs.length
          }
          onClick={() => void save()}
          type="button"
        >
          {saving
            ? "Saving…"
            : definition.id
              ? "Save new Definition version"
              : "Create Workflow"}
        </button>
      </div>
    </section>
  );
}
