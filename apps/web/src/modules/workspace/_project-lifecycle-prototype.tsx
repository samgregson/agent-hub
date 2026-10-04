"use client";

import { useState } from "react";

import { ProjectWorkflowPrototype } from "./_project-workflow-prototype";
import styles from "./project-lifecycle-prototype.module.css";

type CatalogKind = "Dataset" | "Transform" | "MCP batch binding";
type CatalogItem = {
  id: string;
  name: string;
  kind: CatalogKind;
  detail: string;
};
type DraftStep = { id: string; assetId: string; dependencies: string[] };

const startingItems: CatalogItem[] = [
  {
    id: "inputs",
    name: "Input set",
    kind: "Dataset",
    detail: "3 records · revision 2 available",
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
    name: "Reference sources",
    kind: "Sources",
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

export function ProjectLifecyclePrototype({
  destination,
  onNavigate,
}: {
  destination: "Overview" | "Data";
  onNavigate: (next: "Overview" | "Data") => void;
}) {
  const [items, setItems] = useState(startingItems);
  const [collection, setCollection] = useState<"Datasets" | "Operations">(
    "Datasets",
  );
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
  const selected = items.find((item) => item.id === selectedId);
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
    setCollection(item.kind === "Dataset" ? "Datasets" : "Operations");
    setCreating(null);
    setEditingItem(false);
    setMobileDetail(true);
    onNavigate("Data");
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
    if (!pendingId || !dependencies.length) return;
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
          onBrowseData={() => onNavigate("Data")}
          onOpenDefinition={openCatalog}
        />
      </div>

      {destination === "Overview" && workflowEditing ? (
        <section className={styles.editor} aria-label="Workflow editor">
          <header className={styles.pageHead}>
            <div>
              <h1>Edit workflow</h1>
              <p>
                Choose reusable Data records, then bind each step to its
                upstream inputs.
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
          <div className={styles.columns}>
            <section
              aria-label="Workflow definition"
              className={styles.listPanel}
            >
              <div className={styles.panelHead}>
                <h2>Definition</h2>
                <button type="button" onClick={() => onNavigate("Data")}>
                  Browse Data
                </button>
              </div>
              <div className={styles.stepList}>
                {allSteps.map((step) => (
                  <button
                    key={step.id}
                    type="button"
                    className={styles.step}
                    onClick={() => editStep(step.id)}
                    aria-current={
                      editingStepId === step.id ? "true" : undefined
                    }
                  >
                    <span>
                      <strong>{step.name}</strong>
                      <small>{step.kind}</small>
                    </span>
                    <span>
                      Needs:{" "}
                      {step.dependencies.length
                        ? step.dependencies
                            .map(
                              (id) =>
                                allSteps.find((item) => item.id === id)?.name,
                            )
                            .join(" + ")
                        : "Project input"}
                    </span>
                  </button>
                ))}
              </div>
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
                Select a Dataset or operation from Data. Dependencies determine
                which captured outputs feed this step.
              </p>
              <button type="button" onClick={() => onNavigate("Data")}>
                Choose from Data
              </button>
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
                    disabled={!dependencies.length}
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
                  Select a step to edit its bindings, or choose a record in Data
                  to add another.
                </p>
              )}
            </section>
          </div>
        </section>
      ) : null}

      {destination === "Data" ? (
        <section
          className={`${styles.data} ${mobileDetail ? styles.mobileDetail : ""}`}
          aria-label="Data catalog"
        >
          <header className={styles.pageHead}>
            <div>
              <h1>Data</h1>
              <p>
                Create and manage Datasets and reusable Operations. Workflow
                steps reference these definitions.
              </p>
            </div>
            <button type="button" onClick={() => onNavigate("Overview")}>
              View workflow
            </button>
          </header>
          <div className={styles.columns}>
            <aside className={styles.listPanel} aria-label="Data collections">
              <div className={styles.tabs} role="group" aria-label="Data type">
                {(["Datasets", "Operations"] as const).map((name) => (
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
                ))}
              </div>
              <div className={styles.panelHead}>
                <h2>{collection}</h2>
                <button
                  type="button"
                  onClick={() => {
                    setCreating(
                      collection === "Datasets" ? "Dataset" : "Transform",
                    );
                    setNewName("");
                    setNewDetail("");
                    setMobileDetail(true);
                  }}
                >
                  Create {collection === "Datasets" ? "Dataset" : "Operation"}
                </button>
              </div>
              <div className={styles.catalogList}>
                {items
                  .filter((item) =>
                    collection === "Datasets"
                      ? item.kind === "Dataset"
                      : item.kind !== "Dataset",
                  )
                  .map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      aria-current={
                        selectedId === item.id && !creating ? "true" : undefined
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
                Runs and Result Sets live under the definition that produced
                them.
              </p>
            </aside>
            <section className={styles.detailPanel} aria-label="Data editor">
              <button
                className={styles.mobileBack}
                type="button"
                onClick={() => setMobileDetail(false)}
              >
                Back to Data
              </button>
              {creating ? (
                <form onSubmit={createItem} className={styles.form}>
                  <h2>
                    Create {creating === "Dataset" ? "Dataset" : "Operation"}
                  </h2>
                  {collection === "Operations" ? (
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
                  ) : null}
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
                (collection === "Datasets"
                  ? selected.kind === "Dataset"
                  : selected.kind !== "Dataset") ? (
                <div className={styles.recordDetail}>
                  <small>{selected.kind}</small>
                  <h2>{selected.name}</h2>
                  <p>{selected.detail}</p>
                  <div className={styles.actions}>
                    <button
                      type="button"
                      onClick={() => {
                        setEditName(selected.name);
                        setEditingItem(true);
                      }}
                    >
                      Edit definition
                    </button>
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
                  {selected.kind !== "Dataset" ? (
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
                    {collection === "Datasets"
                      ? "Dataset"
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
