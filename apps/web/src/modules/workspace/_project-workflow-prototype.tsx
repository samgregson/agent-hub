"use client";

import { useState } from "react";

import styles from "./project-workflow-prototype.module.css";

type NodeKey =
  "inputs" | "references" | "evaluate" | "extract" | "findings" | "review";
type RunNumber = 1 | 2;

type WorkflowNode = {
  key: NodeKey;
  title: string;
  kind: string;
  dependsOn: NodeKey[];
  output: string;
  record: string;
  x: number;
  y: number;
};

const nodes: WorkflowNode[] = [
  {
    key: "inputs",
    title: "Input set",
    kind: "Dataset",
    dependsOn: [],
    output: "Captured records",
    record: "Dataset · Input set",
    x: 2,
    y: 12,
  },
  {
    key: "references",
    title: "Reference sources",
    kind: "Sources",
    dependsOn: [],
    output: "Selected documents",
    record: "Project Sources",
    x: 2,
    y: 61,
  },
  {
    key: "evaluate",
    title: "Evaluate records",
    kind: "MCP Batch",
    dependsOn: ["inputs"],
    output: "Result Set",
    record: "Batch Run and Result Set",
    x: 28,
    y: 12,
  },
  {
    key: "extract",
    title: "Extract criteria",
    kind: "MCP tool",
    dependsOn: ["references"],
    output: "Retained tool result",
    record: "MCP result snapshot",
    x: 28,
    y: 61,
  },
  {
    key: "findings",
    title: "Select findings",
    kind: "Transform",
    dependsOn: ["evaluate"],
    output: "Selected values",
    record: "Transform Run",
    x: 54,
    y: 12,
  },
  {
    key: "review",
    title: "Draft review",
    kind: "MCP tool · Bindings",
    dependsOn: ["findings", "extract"],
    output: "Draft output",
    record: "Retained tool result",
    x: 79,
    y: 38,
  },
];

const nodeByKey = Object.fromEntries(
  nodes.map((node) => [node.key, node]),
) as Record<NodeKey, WorkflowNode>;

const edges: { from: NodeKey; to: NodeKey; path: string }[] = [
  { from: "inputs", to: "evaluate", path: "M200 80 L280 80" },
  { from: "references", to: "extract", path: "M200 255 L280 255" },
  { from: "evaluate", to: "findings", path: "M460 80 L540 80" },
  { from: "findings", to: "review", path: "M720 80 C755 80 740 160 790 176" },
  { from: "extract", to: "review", path: "M460 255 C650 255 690 176 790 176" },
];

const outcomes: Record<RunNumber, Record<NodeKey, string>> = {
  1: {
    inputs: "Input set revision 1 was captured for this Run.",
    references: "Two Project Sources were captured for this Run.",
    evaluate: "3 records evaluated; 2 findings retained in a Result Set.",
    extract: "Review criteria were extracted into a retained tool result.",
    findings: "2 findings selected from the Result Set.",
    review:
      "The draft combines 2 selected findings with the extracted criteria.",
  },
  2: {
    inputs: "Input set revision 2 was captured for this Run.",
    references: "The same two Project Sources were captured for this Run.",
    evaluate: "3 records evaluated; 1 finding retained in a new Result Set.",
    extract: "Review criteria were extracted into a new retained tool result.",
    findings: "1 finding selected from the new Result Set.",
    review:
      "The revised draft combines 1 selected finding with the extracted criteria.",
  },
};

function recordLabel(node: WorkflowNode, run: RunNumber) {
  if (node.key === "evaluate")
    return `BR-${run === 1 ? "204" : "205"} · ${node.record}`;
  if (node.key === "findings")
    return `TR-${run === 1 ? "103" : "104"} · ${node.record}`;
  return node.record;
}

export function ProjectWorkflowPrototype() {
  const [inputRevision, setInputRevision] = useState<"1" | "2">("1");
  const [latestRun, setLatestRun] = useState<RunNumber>(1);
  const [viewedRun, setViewedRun] = useState<RunNumber>(1);
  const [selectedNode, setSelectedNode] = useState<NodeKey>("review");
  const [detailOpen, setDetailOpen] = useState(false);
  const [showRecord, setShowRecord] = useState(false);
  const [viewMode, setViewMode] = useState<"map" | "outline">("map");
  const selected = nodeByKey[selectedNode];

  function runRevision() {
    if (inputRevision !== "2" || latestRun === 2) return;
    setLatestRun(2);
    setViewedRun(2);
    setSelectedNode("review");
    setDetailOpen(false);
    setShowRecord(false);
  }

  function openNode(key: NodeKey) {
    setSelectedNode(key);
    setDetailOpen(true);
    setShowRecord(false);
  }

  function viewRun(run: RunNumber) {
    setViewedRun(run);
    setDetailOpen(false);
    setShowRecord(false);
  }

  return (
    <div
      className={`${styles.workflow} ${detailOpen ? styles.detailOpen : ""}`}
    >
      <header className={styles.overviewHeader}>
        <div>
          <h1>Design review</h1>
          <p>
            Project inputs and reference criteria feed the review. Inspect any
            dependency to trace its captured result.
          </p>
        </div>
        <span className={styles.workflowType}>Workflow · Project overview</span>
      </header>

      <div className={styles.runBanner}>
        <div>
          <strong>Workflow Run {viewedRun}</strong>
          <span>
            {viewedRun === 1
              ? "Completed · 2 findings · no tool errors"
              : "Completed · 1 finding · no tool errors"}
          </span>
        </div>
        <span className={styles.runState}>Captured execution</span>
      </div>
      {viewedRun === 2 ? (
        <p className={styles.comparison}>
          Compared with Run 1: input set revision 1 → 2; selected findings 2 →
          1. The earlier Run and its outputs remain available.
        </p>
      ) : null}

      <div className={styles.layout}>
        <div className={styles.mainColumn}>
          <section
            className={styles.graphSection}
            aria-label="Workflow dependencies"
          >
            <div className={styles.sectionHeading}>
              <div>
                <h2>Dependencies</h2>
                <p>
                  Two branches converge on the draft. Select a node to inspect
                  its inputs and output.
                </p>
              </div>
              <div
                className={styles.viewToggle}
                role="group"
                aria-label="Dependency view"
              >
                <button
                  type="button"
                  aria-pressed={viewMode === "map"}
                  onClick={() => setViewMode("map")}
                >
                  Map
                </button>
                <button
                  type="button"
                  aria-pressed={viewMode === "outline"}
                  onClick={() => setViewMode("outline")}
                >
                  Outline
                </button>
              </div>
            </div>

            <div
              className={`${styles.map} ${viewMode === "map" ? styles.active : ""}`}
              aria-label="Read-only dependency map"
            >
              <svg
                viewBox="0 0 1000 350"
                preserveAspectRatio="none"
                aria-hidden="true"
              >
                <defs>
                  <marker
                    id="workflow-arrow"
                    markerWidth="7"
                    markerHeight="7"
                    refX="6"
                    refY="3.5"
                    orient="auto"
                  >
                    <path d="M0 0 L7 3.5 L0 7" />
                  </marker>
                </defs>
                {edges.map((edge) => (
                  <path
                    key={`${edge.from}-${edge.to}`}
                    d={edge.path}
                    markerEnd="url(#workflow-arrow)"
                  />
                ))}
              </svg>
              {nodes.map((node) => (
                <button
                  key={node.key}
                  className={styles.mapNode}
                  style={{ left: `${node.x}%`, top: `${node.y}%` }}
                  type="button"
                  aria-current={selectedNode === node.key ? "true" : undefined}
                  onClick={() => openNode(node.key)}
                >
                  <small>{node.kind}</small>
                  <strong>{node.title}</strong>
                </button>
              ))}
            </div>

            <div
              className={`${styles.outline} ${viewMode === "outline" ? styles.active : ""}`}
              aria-label="Dependency outline"
            >
              {nodes.map((node) => (
                <button
                  key={node.key}
                  type="button"
                  aria-current={selectedNode === node.key ? "true" : undefined}
                  onClick={() => openNode(node.key)}
                >
                  <span>
                    <strong>{node.title}</strong>
                    <small>{node.kind}</small>
                  </span>
                  <span>
                    Needs:{" "}
                    {node.dependsOn.length
                      ? node.dependsOn
                          .map((key) => nodeByKey[key].title)
                          .join(" + ")
                      : "Project input"}
                  </span>
                </button>
              ))}
            </div>
          </section>

          <section
            className={styles.nodeDetail}
            aria-label="Selected Workflow node"
          >
            <button
              className={styles.mobileBack}
              type="button"
              onClick={() => setDetailOpen(false)}
            >
              Back to Workflow
            </button>
            <div className={styles.sectionHeading}>
              <h2>{selected.title}</h2>
              <span>{selected.kind}</span>
            </div>
            <p className={styles.outcome}>
              {outcomes[viewedRun][selectedNode]}
            </p>
            <dl className={styles.lineage}>
              <div>
                <dt>Depends on</dt>
                <dd>
                  {selected.dependsOn.length
                    ? selected.dependsOn
                        .map((key) => nodeByKey[key].title)
                        .join(" + ")
                    : "Project input"}
                </dd>
              </div>
              <div>
                <dt>Produces</dt>
                <dd>{selected.output}</dd>
              </div>
              <div>
                <dt>Captured record</dt>
                <dd>{recordLabel(selected, viewedRun)}</dd>
              </div>
            </dl>
            <button
              className={styles.recordLink}
              type="button"
              aria-expanded={showRecord}
              onClick={() => setShowRecord((current) => !current)}
            >
              {showRecord ? "Close captured record" : "Inspect captured record"}
            </button>
            {showRecord ? (
              <div className={styles.recordSnapshot}>
                <strong>{recordLabel(selected, viewedRun)}</strong>
                <p>
                  Workflow Run {viewedRun} · Captured input:{" "}
                  {selected.dependsOn.length
                    ? selected.dependsOn
                        .map((key) => nodeByKey[key].output)
                        .join(" + ")
                    : selected.title}
                </p>
                <p>Stored output: {outcomes[viewedRun][selectedNode]}</p>
              </div>
            ) : null}
            <p className={styles.detailFoot}>
              This is the captured result from Workflow Run {viewedRun}. Preview
              settings do not change this dependency or its downstream output.
            </p>
          </section>
        </div>

        <aside
          className={styles.sideColumn}
          aria-label="Workflow runs and inputs"
        >
          <section className={styles.inputSection}>
            <h2>Run with revised inputs</h2>
            <p>
              Choose the input set for another execution. Earlier Runs remain
              inspectable.
            </p>
            <label>
              Input set
              <select
                value={inputRevision}
                onChange={(event) =>
                  setInputRevision(event.target.value as "1" | "2")
                }
              >
                <option value="1">Revision 1 · current Run</option>
                <option value="2">Revision 2 · updated values</option>
              </select>
            </label>
            <button
              className={styles.runButton}
              type="button"
              disabled={inputRevision !== "2" || latestRun === 2}
              onClick={runRevision}
            >
              {latestRun === 2 ? "Revised Run created" : "Run Workflow"}
            </button>
            <small>
              An agent-proposed input change and durable Run would pause for
              approval.
            </small>
          </section>

          <section className={styles.historySection}>
            <h2>Run history</h2>
            <button
              type="button"
              aria-current={viewedRun === 1 ? "true" : undefined}
              onClick={() => viewRun(1)}
            >
              <strong>Run 1 · input revision 1</strong>
              <span>2 findings</span>
            </button>
            {latestRun === 2 ? (
              <button
                type="button"
                aria-current={viewedRun === 2 ? "true" : undefined}
                onClick={() => viewRun(2)}
              >
                <strong>Run 2 · input revision 2</strong>
                <span>1 finding</span>
              </button>
            ) : null}
          </section>
          <p className={styles.scopeNote}>
            Each Run retains its input snapshot, decisions, and linked outputs.
          </p>
        </aside>
      </div>
    </div>
  );
}
