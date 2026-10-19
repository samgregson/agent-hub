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
  inputTypes: Record<string, string>;
  inputSchema: Record<string, unknown> | null;
  outputSchema: Record<string, unknown> | null;
  repeatSafe: boolean;
};

type EditorCatalog = {
  error: string | null;
  warning: string | null;
  items: AddableNode[] | null;
};

function schemaFieldPaths(value: Record<string, unknown> | null) {
  if (!value) return [];
  const paths: string[] = [];
  const visit = (schema: Record<string, unknown>, prefix: string) => {
    const properties = schema.properties;
    if (
      !properties ||
      typeof properties !== "object" ||
      Array.isArray(properties)
    )
      return;
    for (const [name, childValue] of Object.entries(properties)) {
      if (
        !childValue ||
        typeof childValue !== "object" ||
        Array.isArray(childValue)
      )
        continue;
      const pointerPart = name.replaceAll("~", "~0").replaceAll("/", "~1");
      const path = `${prefix}/${pointerPart}`;
      paths.push(path);
      visit(childValue as Record<string, unknown>, path);
    }
  };
  visit(value, "");
  return paths;
}

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
  const [graph, setGraph] = useState<EditableGraph>(() => ({
    ...structuredClone(definition.graph),
    inputs: structuredClone(definition.graph.inputs ?? []),
  }));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [catalog, setCatalog] = useState<EditorCatalog>({
    error: null,
    warning: null,
    items: null,
  });
  const [selectedAddableNode, setSelectedAddableNode] = useState("");
  const [newNodeShape, setNewNodeShape] = useState<"single" | "map">("single");
  const [inputSchemaText, setInputSchemaText] = useState(() =>
    (definition.graph.inputs ?? []).map((input) =>
      JSON.stringify(input.schema, null, 2),
    ),
  );
  const [inputSchemaErrors, setInputSchemaErrors] = useState<
    Record<number, string>
  >({});
  const [literalText, setLiteralText] = useState(() =>
    definition.graph.edges.map((edge) =>
      JSON.stringify(edge.literal ?? null, null, 2),
    ),
  );
  const [literalErrors, setLiteralErrors] = useState<Record<number, string>>(
    {},
  );

  useEffect(() => {
    let active = true;
    const root = `/api/projects/${encodeURIComponent(projectId)}`;
    void Promise.all([
      fetch(`${root}/datasets`, { cache: "no-store" }),
      fetch(`${root}/files/index`, { cache: "no-store" }),
      fetch(`${root}/functions`, { cache: "no-store" }),
      fetch(`${root}/plugins`, { cache: "no-store" }),
    ])
      .then(async (responses) => {
        if (responses.some((response) => !response.ok)) {
          throw new Error(
            "Library items and Workflow call targets could not be loaded.",
          );
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
            inputSchema: Record<string, unknown> & {
              properties?: Record<string, unknown>;
            };
            outputSchema?: Record<string, unknown>;
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
            inputTypes: {},
            inputSchema: null,
            outputSchema: null,
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
              inputTypes: {},
              inputSchema: null,
              outputSchema: null,
              repeatSafe: false,
            })),
          ...functions.map((definition) => ({
            id: definition.id,
            label: `Function · ${definition.name}`,
            kind: "python" as const,
            version: definition.revision,
            inputPorts: Object.keys(definition.inputSchema.properties ?? {}),
            inputTypes: Object.fromEntries(
              Object.entries(definition.inputSchema.properties ?? {}).flatMap(
                ([name, schema]) => {
                  if (!schema || typeof schema !== "object") return [];
                  const type = (schema as { type?: unknown }).type;
                  return typeof type === "string" ? [[name, type]] : [];
                },
              ),
            ),
            inputSchema: definition.inputSchema,
            outputSchema: definition.outputSchema ?? null,
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
                  inputSchema: Record<string, unknown> & {
                    properties?: Record<string, unknown>;
                  };
                  outputSchema?: Record<string, unknown>;
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
              inputTypes: Object.fromEntries(
                Object.entries(tool.inputSchema.properties ?? {}).flatMap(
                  ([name, schema]) => {
                    if (!schema || typeof schema !== "object") return [];
                    const type = (schema as { type?: unknown }).type;
                    return typeof type === "string" ? [[name, type]] : [];
                  },
                ),
              ),
              inputSchema: tool.inputSchema,
              outputSchema: tool.outputSchema ?? null,
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
                : "Library items and Workflow call targets could not be loaded.",
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
        : [
            "items",
            ...(item?.inputPorts ?? []).filter(
              (port) => port !== node.mapInput,
            ),
          ];
    return item?.inputPorts ?? [];
  }

  function nodeName(nodeId: string | null) {
    const node = graph.nodes.find((candidate) => candidate.id === nodeId);
    if (!node) return "unselected source";
    const item = catalog.items?.find(
      (candidate) =>
        candidate.id === node.refId &&
        candidate.kind === node.kind &&
        candidate.toolName === node.toolName,
    );
    return item?.label ?? `${node.kind} · ${node.id}`;
  }

  function targetInputType(edge: EditableGraph["edges"][number]) {
    if (edge.targetPort === "items") return "array";
    const node = graph.nodes.find(
      (candidate) => candidate.id === edge.targetNode,
    );
    if (!node) return "json";
    return (
      catalog.items?.find(
        (candidate) =>
          candidate.id === node.refId &&
          candidate.kind === node.kind &&
          candidate.toolName === node.toolName,
      )?.inputTypes[edge.targetPort] ?? "json"
    );
  }

  function sourcePathOptions(edge: EditableGraph["edges"][number]) {
    if (edge.sourceKind === "workflowInput") {
      const input = graph.inputs.find((item) => item.name === edge.sourceInput);
      return schemaFieldPaths(input?.schema ?? null);
    }
    const node = graph.nodes.find(
      (candidate) => candidate.id === edge.sourceNode,
    );
    if (!node) return [];
    const item = catalog.items?.find(
      (candidate) =>
        candidate.id === node.refId &&
        candidate.kind === node.kind &&
        candidate.toolName === node.toolName,
    );
    return schemaFieldPaths(item?.outputSchema ?? null);
  }

  function targetPathOptions(edge: EditableGraph["edges"][number]) {
    const node = graph.nodes.find(
      (candidate) => candidate.id === edge.targetNode,
    );
    if (!node) return [];
    const item = catalog.items?.find(
      (candidate) =>
        candidate.id === node.refId &&
        candidate.kind === node.kind &&
        candidate.toolName === node.toolName,
    );
    const properties = item?.inputSchema?.properties;
    const targetSchema =
      properties && typeof properties === "object" && !Array.isArray(properties)
        ? (properties as Record<string, unknown>)[edge.targetPort]
        : undefined;
    return schemaFieldPaths(
      targetSchema &&
        typeof targetSchema === "object" &&
        !Array.isArray(targetSchema)
        ? (targetSchema as Record<string, unknown>)
        : null,
    );
  }

  function bindingSummary(edge: EditableGraph["edges"][number]) {
    const pointer = (path: string | undefined) => {
      if (!path) return "whole value";
      return path
        .split("/")
        .slice(1)
        .map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~"))
        .join(" → ");
    };
    const source =
      edge.sourceKind === "workflowInput"
        ? `Workflow Input · ${edge.sourceInput ?? "unnamed"}`
        : edge.sourceKind === "literal"
          ? "Literal value"
          : nodeName(edge.sourceNode);
    const targetNode = graph.nodes.find((node) => node.id === edge.targetNode);
    const targetRole =
      targetNode?.shape === "map"
        ? edge.targetPort === "items" || edge.targetPort === targetNode.mapInput
          ? "Map item"
          : "Shared input"
        : "Input";
    return `${source} · ${pointer(edge.sourcePath)} → ${nodeName(edge.targetNode)} · ${targetRole} ${edge.targetPort}${edge.targetPath ? ` · ${pointer(edge.targetPath)}` : ""}`;
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
        (item.kind === "mcp" ? item.repeatSafe : item.inputPorts.length >= 1)
          ? "map"
          : "single",
      ...((item.kind === "python" || item.kind === "mcp") &&
      newNodeShape === "map" &&
      item.kind === "python"
        ? { mapInput: item.inputPorts[0] ?? null }
        : {}),
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

  function updateInput(
    index: number,
    patch: Partial<EditableGraph["inputs"][number]>,
  ) {
    setGraph((current) => ({
      ...current,
      inputs: current.inputs.map((input, inputIndex) =>
        inputIndex === index ? { ...input, ...patch } : input,
      ),
      edges: current.edges.map((edge) =>
        patch.name &&
        edge.sourceKind === "workflowInput" &&
        edge.sourceInput === current.inputs[index]?.name
          ? { ...edge, sourceInput: patch.name }
          : edge,
      ),
    }));
  }

  function changeInputSchema(index: number, value: string) {
    setInputSchemaText((current) =>
      current.map((item, itemIndex) => (itemIndex === index ? value : item)),
    );
    try {
      const schema = JSON.parse(value) as Record<string, unknown>;
      setInputSchemaErrors((current) => {
        const next = { ...current };
        delete next[index];
        return next;
      });
      updateInput(index, { schema });
    } catch {
      setInputSchemaErrors((current) => ({
        ...current,
        [index]: "Enter a valid JSON Schema.",
      }));
    }
  }

  function changeLiteral(index: number, value: string) {
    setLiteralText((current) =>
      current.map((item, itemIndex) => (itemIndex === index ? value : item)),
    );
    try {
      const literal: unknown = JSON.parse(value);
      setLiteralErrors((current) => {
        const next = { ...current };
        delete next[index];
        return next;
      });
      updateEdge(index, { literal });
    } catch {
      setLiteralErrors((current) => ({
        ...current,
        [index]: "Enter a valid JSON value.",
      }));
    }
  }

  return (
    <section aria-label="Edit Workflow Definition" className={styles.editor}>
      <div className={styles.sectionHeading}>
        <div>
          <h2>Edit Workflow Definition</h2>
          <p>
            Add nodes and bind values into named inputs. JSON Pointer paths such
            as /metadata/id select or assemble fields; leave a path empty to use
            the whole value. Existing Runs keep their captured Definition.
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
                {node.shape === "map" && node.kind === "python" ? (
                  <label>
                    <span>Mapped Function input</span>
                    <select
                      onChange={(event) =>
                        setGraph((current) => ({
                          ...current,
                          nodes: current.nodes.map((candidate) =>
                            candidate.id === node.id
                              ? { ...candidate, mapInput: event.target.value }
                              : candidate,
                          ),
                        }))
                      }
                      value={node.mapInput ?? ""}
                    >
                      {(
                        catalog.items?.find(
                          (candidate) =>
                            candidate.id === node.refId &&
                            candidate.kind === "python",
                        )?.inputPorts ?? []
                      ).map((port) => (
                        <option key={port} value={port}>
                          {port}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
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
          <p role="status">Loading Library items and Workflow call targets…</p>
        ) : catalog.items.length === 0 ? (
          <p>
            No eligible Library items or Workflow call targets are available.
          </p>
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
                        ? selectedAddableItem.inputPorts.length === 0
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

      <section
        aria-label="Workflow Inputs editor"
        className={styles.editorGroup}
      >
        <div className={styles.sectionHeading}>
          <h3>Workflow Inputs</h3>
          <button
            onClick={() => {
              setGraph((current) => ({
                ...current,
                inputs: [
                  ...current.inputs,
                  {
                    name: `input${current.inputs.length + 1}`,
                    schema: { type: "string" },
                    required: true,
                  },
                ],
              }));
              setInputSchemaText((current) => [
                ...current,
                '{\n  "type": "string"\n}',
              ]);
            }}
            type="button"
          >
            Add Workflow Input
          </button>
        </div>
        {graph.inputs.map((input, index) => (
          <article className={styles.editorRow} key={`workflow-input-${index}`}>
            <label>
              <span>Name</span>
              <input
                onChange={(event) =>
                  updateInput(index, { name: event.target.value })
                }
                value={input.name}
              />
            </label>
            <label>
              <span>JSON Schema</span>
              <textarea
                aria-label={`Schema for Workflow Input ${input.name}`}
                onChange={(event) =>
                  changeInputSchema(index, event.target.value)
                }
                rows={4}
                value={inputSchemaText[index] ?? "{}"}
              />
            </label>
            <label>
              <input
                checked={input.required}
                onChange={(event) =>
                  updateInput(index, { required: event.target.checked })
                }
                type="checkbox"
              />
              Required at run time
            </label>
            {inputSchemaErrors[index] ? (
              <span role="alert">{inputSchemaErrors[index]}</span>
            ) : null}
            <button
              aria-label={`Remove Workflow Input ${input.name}`}
              onClick={() => {
                setGraph((current) => ({
                  ...current,
                  inputs: current.inputs.filter(
                    (_, inputIndex) => inputIndex !== index,
                  ),
                  edges: current.edges.filter(
                    (edge) =>
                      !(
                        edge.sourceKind === "workflowInput" &&
                        edge.sourceInput === input.name
                      ),
                  ),
                }));
                setInputSchemaText((current) =>
                  current.filter((_, inputIndex) => inputIndex !== index),
                );
              }}
              type="button"
            >
              Remove
            </button>
          </article>
        ))}
      </section>

      <section aria-label="Workflow bindings" className={styles.editorGroup}>
        <div className={styles.sectionHeading}>
          <h3>Bindings</h3>
          <button
            onClick={() => {
              setGraph((current) => ({
                ...current,
                edges: [
                  ...current.edges,
                  {
                    sourceKind: "node",
                    sourceNode: current.nodes[0]?.id ?? "",
                    sourcePort: outputPortFor(current.nodes[0]?.id ?? ""),
                    targetNode: current.nodes.at(-1)?.id ?? "",
                    targetPort: inputPortFor(current.nodes.at(-1)?.id ?? ""),
                  },
                ],
              }));
              setLiteralText((current) => [...current, "null"]);
            }}
            type="button"
          >
            Add binding
          </button>
        </div>
        <p className={styles.bindingHelp}>
          Each connection below shows its source and destination. The assembled
          values cannot be resolved here when they depend on current Dataset or
          Project File contents, upstream steps that have not run, or Workflow
          Inputs that will be supplied at Run time. Those values are captured
          and shown in the Run record. Known schema paths are offered as
          suggestions; advanced JSON Pointer paths remain editable.
        </p>
        {graph.edges.map((edge, index) => (
          <div className={styles.editorRow} key={`edge-${index}`}>
            <p className={styles.bindingSummary}>{bindingSummary(edge)}</p>
            <label>
              <span>Value comes from</span>
              <select
                onChange={(event) => {
                  const sourceKind = event.target.value as
                    "node" | "workflowInput" | "literal";
                  const literalType = targetInputType(edge);
                  const defaultLiteral =
                    literalType === "string"
                      ? ""
                      : literalType === "number" || literalType === "integer"
                        ? 0
                        : literalType === "boolean"
                          ? false
                          : null;
                  updateEdge(index, {
                    sourceKind,
                    sourceNode:
                      sourceKind === "node"
                        ? (graph.nodes[0]?.id ?? null)
                        : null,
                    sourcePort:
                      sourceKind === "node"
                        ? outputPortFor(graph.nodes[0]?.id ?? "")
                        : null,
                    sourceInput:
                      sourceKind === "workflowInput"
                        ? (graph.inputs[0]?.name ?? null)
                        : null,
                    literal:
                      sourceKind === "literal" ? defaultLiteral : undefined,
                  });
                  if (sourceKind === "literal") {
                    setLiteralText((current) =>
                      current.map((text, i) =>
                        i === index ? JSON.stringify(defaultLiteral) : text,
                      ),
                    );
                    setLiteralErrors((current) => {
                      const next = { ...current };
                      delete next[index];
                      return next;
                    });
                  }
                }}
                value={edge.sourceKind ?? "node"}
              >
                <option value="node">Node output</option>
                <option
                  disabled={graph.inputs.length === 0}
                  value="workflowInput"
                >
                  Workflow Input
                </option>
                <option value="literal">Literal value</option>
              </select>
            </label>
            {edge.sourceKind === "workflowInput" ? (
              <label>
                <span>Workflow Input</span>
                <select
                  onChange={(event) =>
                    updateEdge(index, { sourceInput: event.target.value })
                  }
                  value={edge.sourceInput ?? ""}
                >
                  {graph.inputs.map((input) => (
                    <option key={input.name} value={input.name}>
                      {input.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {edge.sourceKind === "node" || !edge.sourceKind ? (
              <>
                <label>
                  <span>From node</span>
                  <select
                    onChange={(event) =>
                      updateEdge(index, {
                        sourceNode: event.target.value,
                        sourcePort: outputPortFor(event.target.value),
                      })
                    }
                    value={edge.sourceNode ?? ""}
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
                  <input readOnly value={edge.sourcePort ?? ""} />
                </label>
              </>
            ) : null}
            {edge.sourceKind === "literal" ? (
              <label>
                <span>
                  {targetInputType(edge) === "json" ||
                  targetInputType(edge) === "object" ||
                  targetInputType(edge) === "array"
                    ? "Literal value (JSON)"
                    : `Literal ${targetInputType(edge)}`}
                </span>
                {targetInputType(edge) === "boolean" ? (
                  <input
                    aria-label={`Literal for binding ${index + 1}`}
                    checked={edge.literal === true}
                    onChange={(event) => {
                      setLiteralText((current) =>
                        current.map((text, itemIndex) =>
                          itemIndex === index
                            ? String(event.target.checked)
                            : text,
                        ),
                      );
                      updateEdge(index, { literal: event.target.checked });
                    }}
                    type="checkbox"
                  />
                ) : targetInputType(edge) === "string" ? (
                  <input
                    aria-label={`Literal for binding ${index + 1}`}
                    onChange={(event) => {
                      setLiteralText((current) =>
                        current.map((text, itemIndex) =>
                          itemIndex === index ? event.target.value : text,
                        ),
                      );
                      updateEdge(index, { literal: event.target.value });
                    }}
                    type="text"
                    value={typeof edge.literal === "string" ? edge.literal : ""}
                  />
                ) : targetInputType(edge) === "number" ||
                  targetInputType(edge) === "integer" ? (
                  <input
                    aria-label={`Literal for binding ${index + 1}`}
                    onChange={(event) =>
                      changeLiteral(index, event.target.value)
                    }
                    step={targetInputType(edge) === "integer" ? "1" : "any"}
                    type="number"
                    value={typeof edge.literal === "number" ? edge.literal : ""}
                  />
                ) : (
                  <textarea
                    aria-label={`Literal for binding ${index + 1}`}
                    onChange={(event) =>
                      changeLiteral(index, event.target.value)
                    }
                    rows={3}
                    value={literalText[index] ?? "null"}
                  />
                )}
                {literalErrors[index] ? (
                  <span role="alert">{literalErrors[index]}</span>
                ) : null}
              </label>
            ) : null}
            <label>
              <span>Source field path</span>
              <input
                aria-label={`Source field path for binding ${index + 1}`}
                list={`workflow-source-paths-${index}`}
                onChange={(event) =>
                  updateEdge(index, { sourcePath: event.target.value })
                }
                placeholder="/field/nested"
                value={edge.sourcePath ?? ""}
              />
              <datalist id={`workflow-source-paths-${index}`}>
                {sourcePathOptions(edge).map((path) => (
                  <option key={path} value={path} />
                ))}
              </datalist>
            </label>
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
            <label>
              <span>Target field path</span>
              <input
                aria-label={`Target field path for binding ${index + 1}`}
                list={`workflow-target-paths-${index}`}
                onChange={(event) =>
                  updateEdge(index, { targetPath: event.target.value })
                }
                placeholder="/field/nested"
                value={edge.targetPath ?? ""}
              />
              <datalist id={`workflow-target-paths-${index}`}>
                {targetPathOptions(edge).map((path) => (
                  <option key={path} value={path} />
                ))}
              </datalist>
            </label>
            <button
              aria-label={`Remove connection ${index + 1}`}
              onClick={() => {
                setGraph((current) => ({
                  ...current,
                  edges: current.edges.filter(
                    (_, edgeIndex) => edgeIndex !== index,
                  ),
                }));
                setLiteralText((current) =>
                  current.filter((_, itemIndex) => itemIndex !== index),
                );
              }}
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
              <span>
                {edge.sourceKind === "workflowInput"
                  ? `Workflow Input · ${edge.sourceInput ?? "missing"}`
                  : edge.sourceKind === "literal"
                    ? `Literal · ${JSON.stringify(edge.literal)}`
                    : edge.sourceNode}
              </span>
              {edge.sourceKind === "node" ? (
                <code>{edge.sourcePort}</code>
              ) : null}
              <span aria-hidden="true">→</span>
              <span>{edge.targetNode}</span>
              <code>{edge.targetPort}</code>
              {edge.sourcePath ? <code>{edge.sourcePath}</code> : null}
              {edge.targetPath ? <code>{edge.targetPath}</code> : null}
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
            !graph.outputs.length ||
            Object.keys(inputSchemaErrors).length > 0 ||
            Object.keys(literalErrors).length > 0
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
