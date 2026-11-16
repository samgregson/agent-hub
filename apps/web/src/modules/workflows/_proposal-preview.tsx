"use client";

import styles from "./workflow-proposal.module.css";

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

export function WorkflowProposalPreview({ args }: { args: unknown }) {
  const fields = record(args);
  const graph = record(fields?.graph_json);
  const changes = record(fields?.changes);
  const source = graph ?? changes;
  if (!source) return null;
  const nodes = (
    Array.isArray(graph?.nodes)
      ? graph.nodes
      : Array.isArray(changes?.add_nodes)
        ? changes.add_nodes
        : []
  )
    .map(record)
    .filter((node): node is Record<string, unknown> => node !== null);
  const edges = (
    Array.isArray(graph?.edges)
      ? graph.edges
      : Array.isArray(changes?.add_edges)
        ? changes.add_edges
        : []
  )
    .map(record)
    .filter((edge): edge is Record<string, unknown> => edge !== null);
  const outputs = Array.isArray(graph?.outputs) ? graph.outputs : [];
  const outputNames = outputs
    .map(record)
    .map((output) => text(output?.name))
    .filter(Boolean);

  return (
    <section className={styles.proposal} aria-label="Proposed workflow">
      <strong>{graph ? "Proposed workflow" : "Proposed additions"}</strong>
      {nodes.length ? (
        <ul className={styles.nodes}>
          {nodes.map((node, index) => {
            const id = text(node.id) ?? `Step ${index + 1}`;
            const kind = text(node.kind) ?? "step";
            const target = text(node.tool_name) ?? text(node.ref_id);
            const incoming = edges.filter((edge) => edge.target_node === id);
            return (
              <li key={`${id}:${index}`}>
                <details>
                  <summary>
                    <strong>{id}</strong>
                    <span>
                      {kind}
                      {node.shape === "map" ? " · each item" : ""}
                    </span>
                  </summary>
                  {target ? <p>Uses: {target}</p> : null}
                  {incoming.length ? (
                    <ul>
                      {incoming.map((edge, edgeIndex) => (
                        <li key={edgeIndex}>
                          {text(edge.target_port) ?? "Input"} ←{" "}
                          {text(edge.source_node) ??
                            text(edge.source_input) ??
                            (edge.source_kind === "literal"
                              ? "Fixed value"
                              : "Source")}
                          {text(edge.source_port)
                            ? ` · ${text(edge.source_port)}`
                            : ""}
                          {text(edge.source_path)
                            ? ` · ${text(edge.source_path)}`
                            : ""}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p>No inputs shown in this proposal.</p>
                  )}
                </details>
              </li>
            );
          })}
        </ul>
      ) : (
        <p>No steps are included in this proposal.</p>
      )}
      {outputs.length ? (
        <p>
          Final {outputs.length === 1 ? "output" : "outputs"}:{" "}
          {outputNames.join(", ") || outputs.length}
        </p>
      ) : null}
      {changes ? (
        <p>
          Only proposed additions are shown; review action details for removals
          and other changes.
        </p>
      ) : null}
      <p>
        Compatible interactive results can be opened after a successful run.
      </p>
    </section>
  );
}
