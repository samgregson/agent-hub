"use client";

import { useState } from "react";

import { ProjectWorkflowPrototype } from "./_project-workflow-prototype";
import styles from "./project-lifecycle-prototype.module.css";

type CatalogKind =
  "Dataset" | "Project File" | "Artifact" | "Transform" | "MCP batch binding";
type CatalogItem = {
  id: string;
  name: string;
  kind: CatalogKind;
  detail: string;
};
type DraftStep = { id: string; assetId: string; dependencies: string[] };
type WorkflowStep = {
  id: string;
  name: string;
  kind: string;
  dependencies: string[];
};

const startingItems: CatalogItem[] = [
  {
    id: "inputs",
    name: "Input set",
    kind: "Dataset",
    detail: "3 records · revision 2 available",
  },
  {
    id: "references",
    name: "Review guidance.txt",
    kind: "Project File",
    detail: "Version 2 · text · reusable input",
  },
  {
    id: "output",
    name: "Review draft",
    kind: "Artifact",
    detail: "Explicitly saved from Workflow Run 1",
  },
  {
    id: "evaluate",
    name: "Evaluate records",
    kind: "MCP batch binding",
    detail: "Maps selected records to an MCP tool",
  },
  {
    id: "findings",
    name: "Select findings",
    kind: "Transform",
    detail: "Selects values from a Result Set",
  },
  {
    id: "review",
    name: "Draft review",
    kind: "MCP batch binding",
    detail: "Combines bound upstream outputs",
  },
];

const initialSteps = [
  {
    id: "inputs",
    name: "Input set",
    kind: "Dataset",
    dependencies: [] as string[],
  },
  {
    id: "references",
    name: "Review guidance",
    kind: "Project File",
    dependencies: [] as string[],
  },
  {
    id: "evaluate",
    name: "Evaluate records",
    kind: "MCP batch binding",
    dependencies: ["inputs"],
  },
  {
    id: "extract",
    name: "Extract criteria",
    kind: "MCP tool",
    dependencies: ["references"],
  },
  {
    id: "findings",
    name: "Select findings",
    kind: "Transform",
    dependencies: ["evaluate"],
  },
  {
    id: "review",
    name: "Draft review",
    kind: "MCP batch binding",
    dependencies: ["findings", "extract"],
  },
];

function DefinitionGraph({
  steps,
  selectedId,
  onSelect,
}: {
  steps: WorkflowStep[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const columns = new Map<number, WorkflowStep[]>();
  const depthById = new Map<string, number>();
  for (const step of steps) {
    const depth = step.dependencies.length
      ? Math.max(...step.dependencies.map((id) => depthById.get(id) ?? 0)) + 1
      : 0;
    depthById.set(step.id, depth);
    columns.set(depth, [...(columns.get(depth) ?? []), step]);
  }
  const width = Math.max(920, columns.size * 225 + 40);
  const height = Math.max(
    350,
    Math.max(...[...columns.values()].map((group) => group.length)) * 118 + 72,
  );
  const positions = new Map<string, { x: number; y: number }>();
  for (const [depth, group] of columns) {
    group.forEach((step, index) => {
      positions.set(step.id, {
        x: 24 + depth * 225,
        y: Math.round(((index + 1) * height) / (group.length + 1) - 39),
      });
    });
  }

  return (
    <>
      <div
        className={styles.graphViewport}
        aria-label="Workflow definition map"
      >
        <div className={styles.graphCanvas} style={{ width, height }}>
          <svg width={width} height={height} aria-hidden="true">
            <defs>
              <marker
                id="definition-arrow"
                markerWidth="7"
                markerHeight="7"
                refX="6"
                refY="3.5"
                orient="auto"
              >
                <path d="M0 0 L7 3.5 L0 7" />
              </marker>
            </defs>
            {steps.flatMap((step) =>
              step.dependencies.map((id, dependencyIndex) => {
                const from = positions.get(id);
                const to = positions.get(step.id);
                if (!from || !to) return null;
                const startX = from.x + 180;
                const endX = to.x - 8;
                const bend = (startX + endX) / 2;
                const startY = from.y + 39;
                const endY =
                  to.y +
                  (step.dependencies.length > 1
                    ? 26 + dependencyIndex * 26
                    : 39);
                const spansColumn =
                  (depthById.get(step.id) ?? 0) - (depthById.get(id) ?? 0) > 1;
                const path = spansColumn
                  ? `M${startX} ${startY} L${startX + 20} ${startY} L${startX + 20} ${height - 22} L${endX - 24} ${height - 22} L${endX - 24} ${endY} L${endX} ${endY}`
                  : `M${startX} ${startY} C${bend} ${startY} ${bend} ${endY} ${endX} ${endY}`;
                return (
                  <path
                    key={`${id}-${step.id}`}
                    data-from={id}
                    data-to={step.id}
                    d={path}
                    markerEnd="url(#definition-arrow)"
                  />
                );
              }),
            )}
          </svg>
          {steps.map((step) => {
            const position = positions.get(step.id)!;
            return (
              <button
                key={step.id}
                type="button"
                className={styles.graphNode}
                style={{ left: position.x, top: position.y }}
                aria-current={selectedId === step.id ? "true" : undefined}
                onClick={() => onSelect(step.id)}
              >
                <small>{step.kind}</small>
                <strong>{step.name}</strong>
              </button>
            );
          })}
        </div>
      </div>
      <div className={styles.stepList} aria-label="Workflow definition outline">
        {steps.map((step) => (
          <button
            key={step.id}
            type="button"
            className={styles.step}
            onClick={() => onSelect(step.id)}
            aria-current={selectedId === step.id ? "true" : undefined}
          >
            <span>
              <strong>{step.name}</strong>
              <small>{step.kind}</small>
            </span>
            <span>
              Needs:{" "}
              {step.dependencies.length
                ? step.dependencies
                    .map((id) => steps.find((item) => item.id === id)?.name)
                    .join(" + ")
                : "Project input"}
            </span>
          </button>
        ))}
      </div>
    </>
  );
}

export function ProjectLifecyclePrototype({
  destination,
  onNavigate,
}: {
  destination: "Overview" | "Library" | "Operations";
  onNavigate: (next: "Overview" | "Library" | "Operations") => void;
}) {
  const [items, setItems] = useState(startingItems);
  const [collection, setCollection] = useState<
    "All" | "Datasets" | "Files" | "Artifacts"
  >("All");
  const [selectedId, setSelectedId] = useState("inputs");
  const [creating, setCreating] = useState<CatalogKind | null>(null);
  const [newName, setNewName] = useState("");
  const [newDetail, setNewDetail] = useState("");
  const [editingItem, setEditingItem] = useState(false);
  const [editName, setEditName] = useState("");
  const [workflowEditing, setWorkflowEditing] = useState(false);
  const [draftSteps, setDraftSteps] = useState<DraftStep[]>([]);
  const [stepBindings, setStepBindings] = useState<Record<string, string[]>>(
    {},
  );
  const [editingStepId, setEditingStepId] = useState<string | null>(null);
  const [editedDependencies, setEditedDependencies] = useState<string[]>([]);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [dependencies, setDependencies] = useState<string[]>([]);
  const [definitionSaved, setDefinitionSaved] = useState(false);
  const [mobileDetail, setMobileDetail] = useState(false);
  const selectedRecord = items.find((item) => item.id === selectedId);
  const selected =
    destination === "Operations" &&
    selectedRecord?.kind !== "Transform" &&
    selectedRecord?.kind !== "MCP batch binding"
      ? items.find((item) => item.id === "evaluate")
      : destination === "Library" &&
          selectedRecord?.kind !== "Dataset" &&
          selectedRecord?.kind !== "Project File" &&
          selectedRecord?.kind !== "Artifact"
        ? items.find((item) => item.id === "inputs")
        : selectedRecord;
  const pending = items.find((item) => item.id === pendingId);
  const allSteps = [
    ...initialSteps.map((step) => ({
      ...step,
      dependencies: stepBindings[step.id] ?? step.dependencies,
    })),
    ...draftSteps.map((step) => ({
      id: step.id,
      name: items.find((item) => item.id === step.assetId)?.name ?? "New step",
      kind: items.find((item) => item.id === step.assetId)?.kind ?? "Operation",
      dependencies: stepBindings[step.id] ?? step.dependencies,
    })),
  ];

  function openCatalog(id: string) {
    const item = items.find((entry) => entry.id === id);
    if (!item) return;
    setSelectedId(id);
    const inLibrary =
      item.kind === "Dataset" ||
      item.kind === "Project File" ||
      item.kind === "Artifact";
    if (inLibrary) setCollection("All");
    setCreating(null);
    setEditingItem(false);
    setMobileDetail(true);
    onNavigate(inLibrary ? "Library" : "Operations");
  }

  function createItem(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!creating || !newName.trim()) return;
    const item = {
      id: `new-${Date.now()}`,
      name: newName.trim(),
      kind: creating,
      detail: newDetail.trim() || "New definition · draft",
    };
    setItems((current) => [...current, item]);
    setSelectedId(item.id);
    if (creating === "Dataset" || creating === "Project File")
      setCollection("All");
    setCreating(null);
    setNewName("");
    setNewDetail("");
    setMobileDetail(true);
  }

  function attachToWorkflow(id: string) {
    setPendingId(id);
    setDependencies([]);
    setWorkflowEditing(true);
    setEditingStepId(null);
    setMobileDetail(false);
    onNavigate("Overview");
  }

  function addStep() {
    if (!pendingId) return;
    const pendingItem = items.find((item) => item.id === pendingId);
    if (
      !dependencies.length &&
      pendingItem?.kind !== "Dataset" &&
      pendingItem?.kind !== "Project File" &&
      pendingItem?.kind !== "Artifact"
    )
      return;
    setDraftSteps((current) => [
      ...current,
      { id: `step-${current.length + 1}`, assetId: pendingId, dependencies },
    ]);
    setPendingId(null);
    setDependencies([]);
    setDefinitionSaved(false);
  }

  function toggleDependency(id: string) {
    setDependencies((current) =>
      current.includes(id)
        ? current.filter((entry) => entry !== id)
        : [...current, id],
    );
  }

  function editStep(id: string) {
    const step = allSteps.find((entry) => entry.id === id);
    if (!step) return;
    setPendingId(null);
    setEditingStepId(id);
    setEditedDependencies(step.dependencies);
  }

  function saveStepBindings() {
    if (!editingStepId) return;
    setStepBindings((current) => ({
      ...current,
      [editingStepId]: editedDependencies,
    }));
    setEditingStepId(null);
    setDefinitionSaved(false);
  }

  return (
    <div className={styles.lifecycle}>
      <div hidden={destination !== "Overview" || workflowEditing}>
        <ProjectWorkflowPrototype
          onEdit={() => setWorkflowEditing(true)}
          onBrowseLibrary={() => onNavigate("Library")}
          onBrowseOperations={() => onNavigate("Operations")}
          onOpenDefinition={openCatalog}
        />
      </div>

      {destination === "Overview" && workflowEditing ? (
        <section className={styles.editor} aria-label="Workflow editor">
          <header className={styles.pageHead}>
            <div>
              <h1>Edit workflow</h1>
              <p>
                Choose content from Library and definitions from Operations,
                then bind each step to its upstream inputs.
              </p>
            </div>
            <button type="button" onClick={() => setWorkflowEditing(false)}>
              View captured Run
            </button>
          </header>
          <p className={styles.notice}>
            You are editing the Definition. Completed Runs keep their captured
            graph and results.
          </p>
          <div className={styles.editorStack}>
            <section
              aria-label="Workflow definition"
              className={styles.listPanel}
            >
              <div className={styles.panelHead}>
                <div>
                  <h2>Definition</h2>
                  <p>
                    Branches and joins follow the current Definition. Select a
                    step to edit its inputs.
                  </p>
                </div>
                <div className={styles.browseActions}>
                  <button type="button" onClick={() => onNavigate("Library")}>
                    Browse Library
                  </button>
                  <button
                    type="button"
                    onClick={() => onNavigate("Operations")}
                  >
                    Browse Operations
                  </button>
                </div>
              </div>
              <DefinitionGraph
                steps={allSteps}
                selectedId={editingStepId}
                onSelect={editStep}
              />
              <button
                className={styles.primary}
                type="button"
                onClick={() => setDefinitionSaved(true)}
              >
                Save definition
              </button>
              {definitionSaved ? (
                <p role="status">
                  Definition saved in this prototype. Captured Runs remain
                  unchanged.
                </p>
              ) : null}
            </section>
            <section
              aria-label="Add workflow step"
              className={styles.composePanel}
            >
              <h2>Add a step</h2>
              <p>
                Select a Library item or Operation. Dependencies determine which
                captured values feed this step.
              </p>
              <div className={styles.browseActions}>
                <button type="button" onClick={() => onNavigate("Library")}>
                  Choose from Library
                </button>
                <button type="button" onClick={() => onNavigate("Operations")}>
                  Choose from Operations
                </button>
              </div>
              {pending ? (
                <div className={styles.pending}>
                  <strong>{pending.name}</strong>
                  <small>{pending.kind}</small>
                  <fieldset>
                    <legend>Inputs from</legend>
                    {allSteps.map((step) => (
                      <label key={step.id}>
                        <input
                          type="checkbox"
                          checked={dependencies.includes(step.id)}
                          onChange={() => toggleDependency(step.id)}
                        />
                        {step.name}
                      </label>
                    ))}
                  </fieldset>
                  <button
                    className={styles.primary}
                    type="button"
                    disabled={
                      !dependencies.length &&
                      pending.kind !== "Dataset" &&
                      pending.kind !== "Project File" &&
                      pending.kind !== "Artifact"
                    }
                    onClick={addStep}
                  >
                    Add to definition
                  </button>
                </div>
              ) : editingStepId ? (
                <div className={styles.pending}>
                  <strong>
                    {allSteps.find((step) => step.id === editingStepId)?.name}
                  </strong>
                  <small>
                    Edit the inputs this step receives. Only earlier steps are
                    available, so the graph stays acyclic.
                  </small>
                  <fieldset>
                    <legend>Inputs from</legend>
                    {allSteps
                      .slice(
                        0,
                        allSteps.findIndex((step) => step.id === editingStepId),
                      )
                      .map((step) => (
                        <label key={step.id}>
                          <input
                            type="checkbox"
                            checked={editedDependencies.includes(step.id)}
                            onChange={() =>
                              setEditedDependencies((current) =>
                                current.includes(step.id)
                                  ? current.filter((entry) => entry !== step.id)
                                  : [...current, step.id],
                              )
                            }
                          />
                          {step.name}
                        </label>
                      ))}
                  </fieldset>
                  <button
                    className={styles.primary}
                    type="button"
                    onClick={saveStepBindings}
                  >
                    Save step bindings
                  </button>
                </div>
              ) : (
                <p className={styles.hint}>
                  Select a step to edit its bindings, or choose a record from
                  Library or Operations to add another.
                </p>
              )}
            </section>
          </div>
        </section>
      ) : null}

      {destination === "Library" || destination === "Operations" ? (
        <section
          className={`${styles.data} ${mobileDetail && selectedId === selected?.id ? styles.mobileDetail : ""}`}
          aria-label={`${destination} catalog`}
        >
          <header className={styles.pageHead}>
            <div>
              <h1>{destination}</h1>
              <p>
                {destination === "Library"
                  ? "Project Files, registered Datasets, and Artifacts share one home with distinct viewers and edit rules."
                  : "Create reusable Transforms and MCP bindings. Runs and results stay with their definitions."}
              </p>
            </div>
            <button type="button" onClick={() => onNavigate("Overview")}>
              View workflow
            </button>
          </header>
          <div className={styles.columns}>
            <aside
              className={styles.listPanel}
              aria-label={`${destination} collections`}
            >
              {destination === "Library" ? (
                <div
                  className={styles.tabs}
                  role="group"
                  aria-label="Library type"
                >
                  {(["All", "Datasets", "Files", "Artifacts"] as const).map(
                    (name) => (
                      <button
                        key={name}
                        type="button"
                        aria-pressed={collection === name}
                        onClick={() => {
                          setCollection(name);
                          setCreating(null);
                          setMobileDetail(false);
                        }}
                      >
                        {name}
                      </button>
                    ),
                  )}
                </div>
              ) : null}
              <div className={styles.panelHead}>
                <h2>
                  {destination === "Library" ? collection : "Definitions"}
                </h2>
                <button
                  type="button"
                  onClick={() => {
                    setCreating(
                      destination === "Library" ? "Dataset" : "Transform",
                    );
                    setNewName("");
                    setNewDetail("");
                    setMobileDetail(true);
                  }}
                >
                  Create{" "}
                  {destination === "Library" ? "Library item" : "Operation"}
                </button>
              </div>
              <div className={styles.catalogList}>
                {items
                  .filter((item) =>
                    destination === "Operations"
                      ? item.kind === "Transform" ||
                        item.kind === "MCP batch binding"
                      : collection === "All"
                        ? item.kind === "Dataset" ||
                          item.kind === "Project File" ||
                          item.kind === "Artifact"
                        : collection === "Datasets"
                          ? item.kind === "Dataset"
                          : collection === "Files"
                            ? item.kind === "Project File"
                            : item.kind === "Artifact",
                  )
                  .map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      aria-current={
                        selected?.id === item.id && !creating
                          ? "true"
                          : undefined
                      }
                      onClick={() => {
                        setSelectedId(item.id);
                        setCreating(null);
                        setEditingItem(false);
                        setMobileDetail(true);
                      }}
                    >
                      <strong>{item.name}</strong>
                      <small>
                        {item.kind} · {item.detail}
                      </small>
                    </button>
                  ))}
              </div>
              <p className={styles.hint}>
                {destination === "Library"
                  ? "Content is grouped for discovery; each type keeps its own identity and write rules."
                  : "Runs and Result Sets remain under their producing definition."}
              </p>
            </aside>
            <section
              className={styles.detailPanel}
              aria-label={`${destination} detail`}
            >
              <button
                className={styles.mobileBack}
                type="button"
                onClick={() => setMobileDetail(false)}
              >
                Back to {destination}
              </button>
              {creating ? (
                <form onSubmit={createItem} className={styles.form}>
                  <h2>Create {creating}</h2>
                  {destination === "Library" ? (
                    <label>
                      Content type
                      <select
                        value={creating}
                        onChange={(event) =>
                          setCreating(event.target.value as CatalogKind)
                        }
                      >
                        <option value="Dataset">Dataset</option>
                        <option value="Project File">Project File</option>
                      </select>
                    </label>
                  ) : (
                    <label>
                      Operation type
                      <select
                        value={creating}
                        onChange={(event) =>
                          setCreating(event.target.value as CatalogKind)
                        }
                      >
                        <option value="Transform">Transform</option>
                        <option value="MCP batch binding">
                          MCP batch binding
                        </option>
                      </select>
                    </label>
                  )}
                  <label>
                    Name
                    <input
                      autoFocus
                      value={newName}
                      onChange={(event) => setNewName(event.target.value)}
                      required
                    />
                  </label>
                  <label>
                    Description
                    <input
                      value={newDetail}
                      onChange={(event) => setNewDetail(event.target.value)}
                    />
                  </label>
                  <div className={styles.actions}>
                    <button className={styles.primary} type="submit">
                      Create draft
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setCreating(null);
                        setMobileDetail(false);
                      }}
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              ) : selected &&
                (destination === "Operations"
                  ? selected.kind === "Transform" ||
                    selected.kind === "MCP batch binding"
                  : collection === "All" ||
                    (collection === "Datasets" &&
                      selected.kind === "Dataset") ||
                    (collection === "Files" &&
                      selected.kind === "Project File") ||
                    (collection === "Artifacts" &&
                      selected.kind === "Artifact")) ? (
                <div className={styles.recordDetail}>
                  <small>{selected.kind}</small>
                  <h2>{selected.name}</h2>
                  <p>{selected.detail}</p>
                  {selected.kind === "Dataset" ? (
                    <section
                      className={styles.contentViewer}
                      aria-label="Dataset viewer"
                    >
                      <h3>Dataset records</h3>
                      <table>
                        <thead>
                          <tr>
                            <th>Source key</th>
                            <th>Case</th>
                            <th>Value</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr>
                            <td>A-01</td>
                            <td>Baseline</td>
                            <td>12</td>
                          </tr>
                          <tr>
                            <td>A-02</td>
                            <td>Revised</td>
                            <td>15</td>
                          </tr>
                          <tr>
                            <td>A-03</td>
                            <td>Control</td>
                            <td>10</td>
                          </tr>
                        </tbody>
                      </table>
                      <p>
                        Record IDs and order are owned by the Dataset, not by
                        generic file editing.
                      </p>
                    </section>
                  ) : selected.kind === "Project File" ? (
                    <section
                      className={styles.contentViewer}
                      aria-label="Project File viewer"
                    >
                      <h3>File preview</h3>
                      <pre>
                        {selected.id === "references"
                          ? "Review the selected findings against the current project criteria.\nPreserve the source and decision for each finding."
                          : "New Project File · preview available after content is saved."}
                      </pre>
                      <p>
                        This file can be bound as an explicit, versioned
                        operation input. Its format depends on the consuming
                        app.
                      </p>
                    </section>
                  ) : selected.kind === "Artifact" ? (
                    <section
                      className={styles.contentViewer}
                      aria-label="Artifact viewer"
                    >
                      <h3>Saved output</h3>
                      <p>
                        Review draft from Workflow Run 1. Open the captured Run
                        to inspect its inputs and producing operations.
                      </p>
                    </section>
                  ) : selected.kind === "Transform" ? (
                    <section
                      className={styles.contentViewer}
                      aria-label="Transform preview"
                    >
                      <h3>Source and preview</h3>
                      <p>
                        Python preview and durable Runs use the same host-side
                        Deno/Pyodide runner. Preview output is transient; a Run
                        captures its chosen input and source version.
                      </p>
                    </section>
                  ) : selected.kind === "MCP batch binding" ? (
                    <section
                      className={styles.contentViewer}
                      aria-label="MCP binding detail"
                    >
                      <h3>Declared input mapping</h3>
                      <p>
                        Selected values map to the MCP tool’s declared
                        arguments. The Workflow Definition names upstream
                        dependencies and invocation cardinality.
                      </p>
                    </section>
                  ) : null}
                  <div className={styles.actions}>
                    {selected.kind !== "Artifact" ? (
                      <button
                        type="button"
                        onClick={() => {
                          setEditName(selected.name);
                          setEditingItem(true);
                        }}
                      >
                        Edit{" "}
                        {selected.kind === "Dataset"
                          ? "Dataset"
                          : selected.kind === "Project File"
                            ? "file"
                            : "definition"}
                      </button>
                    ) : null}
                    <button
                      className={styles.primary}
                      type="button"
                      onClick={() => attachToWorkflow(selected.id)}
                    >
                      Use in workflow
                    </button>
                  </div>
                  {editingItem ? (
                    <form
                      className={styles.form}
                      onSubmit={(event) => {
                        event.preventDefault();
                        setItems((current) =>
                          current.map((item) =>
                            item.id === selected.id
                              ? { ...item, name: editName.trim() || item.name }
                              : item,
                          ),
                        );
                        setEditingItem(false);
                      }}
                    >
                      <label>
                        Name
                        <input
                          value={editName}
                          onChange={(event) => setEditName(event.target.value)}
                        />
                      </label>
                      <button className={styles.primary} type="submit">
                        Save changes
                      </button>
                    </form>
                  ) : null}
                  <section className={styles.context}>
                    <h3>Used by workflow</h3>
                    <p>
                      {initialSteps.some((step) => step.id === selected.id) ||
                      draftSteps.some((step) => step.assetId === selected.id)
                        ? "Design review · inspect its bindings in the Workflow Definition"
                        : "No workflow steps use this record yet."}
                    </p>
                    <button
                      type="button"
                      onClick={() => {
                        setWorkflowEditing(true);
                        onNavigate("Overview");
                      }}
                    >
                      Open workflow definition
                    </button>
                  </section>
                  {destination === "Operations" ? (
                    <section className={styles.context}>
                      <h3>Runs and results</h3>
                      <p>
                        {selected.id === "evaluate"
                          ? "BR-204 · completed Batch Run · retained Result Set"
                          : selected.id === "findings"
                            ? "TR-103 · completed Transform Run"
                            : selected.id === "review"
                              ? "Captured output in Workflow Run 1"
                              : "No Runs yet. Completed Runs will remain available here."}
                      </p>
                      <p>
                        Saved preview filters, sort, and limit affect inspection
                        only. Every durable Run captures its selected input
                        independently.
                      </p>
                      {initialSteps.some((step) => step.id === selected.id) ? (
                        <button
                          type="button"
                          onClick={() => {
                            setWorkflowEditing(false);
                            onNavigate("Overview");
                          }}
                        >
                          Inspect captured Run
                        </button>
                      ) : null}
                    </section>
                  ) : null}
                </div>
              ) : (
                <div className={styles.empty}>
                  <h2>Select a record</h2>
                  <p>
                    Choose a{" "}
                    {destination === "Library"
                      ? "Project File, Dataset, or Artifact"
                      : "Transform or MCP batch binding"}{" "}
                    to inspect or edit it.
                  </p>
                </div>
              )}
            </section>
          </div>
        </section>
      ) : null}
    </div>
  );
}
