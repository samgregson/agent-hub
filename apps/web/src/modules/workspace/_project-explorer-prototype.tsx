"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import { ProjectLifecyclePrototype } from "./_project-lifecycle-prototype";
import styles from "./project-explorer-prototype.module.css";

// Throwaway issue #37 prototype: compare navigation structures using the
// same illustrative Project records. Nothing here reads or writes Project data.
type Variant = "A" | "B" | "C" | "D" | "E";
type Destination =
  "Overview" | "Chats" | "Work" | "Data" | "Sources" | "Plugins";
type Collection =
  "Datasets" | "Transform Definitions" | "Batch Definitions" | "Operations";
type RecordKey =
  | "dataset"
  | "transform"
  | "transformRun"
  | "batch"
  | "batchRun"
  | "result"
  | "artifact";
type OperationKey = "transform" | "batch";
type PreviewSource = "dataset" | "result" | "tool";
type PreviewDefaults = {
  source: PreviewSource;
  filter: "all" | "high";
  sort: "source" | "load";
  limit: "all" | "2";
};

const sampleValues: Record<
  PreviewSource,
  { sourceKey: string; load: number }[]
> = {
  dataset: [
    { sourceKey: "B-12", load: 9 },
    { sourceKey: "B-13", load: 7.5 },
    { sourceKey: "B-14", load: 9 },
  ],
  result: [
    { sourceKey: "B-12", load: 9 },
    { sourceKey: "B-13", load: 7.5 },
    { sourceKey: "B-14", load: 9 },
  ],
  tool: [
    { sourceKey: "MCP-01", load: 11 },
    { sourceKey: "MCP-02", load: 8 },
    { sourceKey: "MCP-03", load: 10 },
  ],
};

const sourceNames: Record<PreviewSource, string> = {
  dataset: "Load cases · Dataset",
  result: "Beam checks · Result Set",
  tool: "Recent check · retained MCP output",
};

const variants: { key: Variant; label: string }[] = [
  { key: "E", label: "Workflow first" },
  { key: "D", label: "Operations" },
  { key: "A", label: "Collection switcher" },
  { key: "B", label: "Expandable outline" },
  { key: "C", label: "Overview index" },
];

const destinations: Destination[] = [
  "Chats",
  "Work",
  "Data",
  "Sources",
  "Plugins",
];
const workflowDestinations: Destination[] = ["Overview", ...destinations];
const collections: Collection[] = [
  "Datasets",
  "Transform Definitions",
  "Batch Definitions",
];
const operationCollections: Collection[] = ["Datasets", "Operations"];

const records: Record<
  RecordKey,
  { name: string; kind: string; detail: string; status?: string }
> = {
  dataset: {
    name: "Load cases",
    kind: "Dataset",
    detail: "128 records · updated 2 Oct",
  },
  transform: {
    name: "Normalize units",
    kind: "Transform Definition",
    detail: "Revision 3 · Python",
  },
  transformRun: {
    name: "Run TR-103",
    kind: "Transform Run",
    detail: "Completed 2 Oct · immutable input snapshot",
    status: "Completed",
  },
  batch: {
    name: "Assess beams",
    kind: "Batch Definition",
    detail: "Load cases → reference-calculation",
  },
  batchRun: {
    name: "Run BR-204",
    kind: "Batch Run",
    detail: "128 records · completed 2 Oct · immutable snapshot",
    status: "Completed",
  },
  result: {
    name: "Results for BR-204",
    kind: "Result Set",
    detail: "128 outcomes · 126 succeeded · 2 failed",
  },
  artifact: {
    name: "Load summary",
    kind: "Artifact",
    detail: "Curated from Results for BR-204",
  },
};

const primaryRecords: Record<Collection, RecordKey[]> = {
  Datasets: ["dataset"],
  "Transform Definitions": ["transform"],
  "Batch Definitions": ["batch"],
  Operations: ["transform", "batch"],
};

const collectionOf: Record<RecordKey, Collection> = {
  dataset: "Datasets",
  transform: "Transform Definitions",
  transformRun: "Transform Definitions",
  batch: "Batch Definitions",
  batchRun: "Batch Definitions",
  result: "Batch Definitions",
  artifact: "Batch Definitions",
};

const linked: Partial<Record<RecordKey, { title: string; keys: RecordKey[] }>> =
  {
    transform: { title: "Runs", keys: ["transformRun"] },
    batch: { title: "Runs", keys: ["batchRun"] },
    batchRun: { title: "Result Set", keys: ["result"] },
  };

function readVariant(): Variant {
  if (typeof window === "undefined") return "E";
  const value = new URLSearchParams(window.location.search).get("variant");
  return value === "A" || value === "B" || value === "C" || value === "D"
    ? value
    : "E";
}

function subscribeVariant(callback: () => void) {
  window.addEventListener("popstate", callback);
  window.addEventListener("prototype-variant-changed", callback);
  return () => {
    window.removeEventListener("popstate", callback);
    window.removeEventListener("prototype-variant-changed", callback);
  };
}

export function ProjectExplorerPrototype() {
  const variant = useSyncExternalStore(
    subscribeVariant,
    readVariant,
    () => "E",
  );
  const [chosenDestination, setChosenDestination] =
    useState<Destination | null>(null);
  const [chosenCollection, setChosenCollection] = useState<Collection | null>(
    null,
  );
  const [chosenSelected, setChosenSelected] = useState<RecordKey | null>(null);
  const destination =
    chosenDestination ?? (variant === "E" ? "Overview" : "Data");
  const collection =
    chosenCollection ??
    (variant === "D" || variant === "E" ? "Operations" : "Datasets");
  const selected = chosenSelected ?? primaryRecords[collection][0];
  const [inspectingFlow, setInspectingFlow] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [mobileDetail, setMobileDetail] = useState(false);
  const [previewDefaults, setPreviewDefaults] = useState<
    Record<OperationKey, PreviewDefaults>
  >({
    transform: {
      source: "result",
      filter: "high",
      sort: "source",
      limit: "2",
    },
    batch: { source: "dataset", filter: "all", sort: "source", limit: "2" },
  });

  function chooseVariant(next: Variant) {
    const url = new URL(window.location.href);
    url.searchParams.set("variant", next);
    window.history.replaceState(null, "", url);
    window.dispatchEvent(new Event("prototype-variant-changed"));
    setChosenDestination(null);
    setChosenCollection(null);
    setChosenSelected(null);
    setInspectingFlow(false);
    setDrawerOpen(false);
    setMobileDetail(false);
  }

  function cycle(delta: number) {
    const index = variants.findIndex((item) => item.key === variant);
    chooseVariant(
      variants[(index + delta + variants.length) % variants.length].key,
    );
  }

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable]")) return;
      event.preventDefault();
      cycle(event.key === "ArrowRight" ? 1 : -1);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [variant]);

  function chooseDestination(next: Destination) {
    setChosenDestination(next);
    if (next === "Work") setChosenSelected("artifact");
    if (next === "Data" && selected === "artifact")
      setChosenSelected(
        primaryRecords[
          variant === "D" || variant === "E" ? "Operations" : collection
        ][0],
      );
    setDrawerOpen(false);
    setMobileDetail(false);
    setInspectingFlow(false);
  }

  function chooseCollection(next: Collection) {
    setChosenDestination("Data");
    setChosenCollection(next);
    setChosenSelected(primaryRecords[next][0]);
    setInspectingFlow(false);
    setMobileDetail(false);
  }

  function openRecord(key: RecordKey) {
    setChosenDestination(key === "artifact" ? "Work" : "Data");
    if (key !== "artifact")
      setChosenCollection(
        variant === "D" || variant === "E"
          ? key === "dataset"
            ? "Datasets"
            : "Operations"
          : collectionOf[key],
      );
    setChosenSelected(key);
    setInspectingFlow(false);
    setDrawerOpen(false);
    setMobileDetail(true);
  }

  const current = selected ? records[selected] : null;

  return (
    <main
      className={`${styles.shell} ${mobileDetail ? styles.mobileDetail : ""}`}
    >
      <header className={styles.topbar}>
        <span className={styles.mark} aria-hidden="true">
          A
        </span>
        <strong>Riverside extension</strong>
        <span className={styles.prototypeTag}>
          Issue #37 · navigable prototype · illustrative data
        </span>
        <button
          className={styles.navigationToggle}
          type="button"
          onClick={() => setDrawerOpen(true)}
          aria-label="Open Project navigation"
        >
          Navigation
        </button>
      </header>

      <nav className={styles.rail} aria-label="Project views">
        {(variant === "E" ? workflowDestinations : destinations).map((item) => (
          <button
            key={item}
            type="button"
            aria-current={destination === item ? "page" : undefined}
            onClick={() => chooseDestination(item)}
          >
            {item}
          </button>
        ))}
      </nav>

      {drawerOpen ? (
        <div className={styles.drawerBackdrop}>
          <aside className={styles.drawer} aria-label="Project navigation">
            <div className={styles.drawerHead}>
              <strong>Project navigation</strong>
              <button type="button" onClick={() => setDrawerOpen(false)}>
                Close
              </button>
            </div>
            <nav aria-label="Project views">
              {(variant === "E" ? workflowDestinations : destinations).map(
                (item) => (
                  <button
                    key={item}
                    type="button"
                    aria-current={destination === item ? "page" : undefined}
                    onClick={() => chooseDestination(item)}
                  >
                    {item}
                  </button>
                ),
              )}
            </nav>
            {destination === "Data" ? (
              <div className={styles.drawerCollections}>
                {(variant === "D" || variant === "E"
                  ? operationCollections
                  : collections
                ).map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => {
                      chooseCollection(item);
                      setDrawerOpen(false);
                    }}
                  >
                    {item}
                  </button>
                ))}
              </div>
            ) : null}
          </aside>
          <button
            className={styles.drawerDismiss}
            type="button"
            aria-label="Close Project navigation"
            onClick={() => setDrawerOpen(false)}
          />
        </div>
      ) : null}

      <section className={styles.workspace}>
        <div
          className={styles.variantBar}
          role="group"
          aria-label="Prototype variants"
        >
          <strong>Compare Project entry points</strong>
          {variants.map((item) => (
            <button
              key={item.key}
              type="button"
              aria-pressed={variant === item.key}
              onClick={() => chooseVariant(item.key)}
            >
              {item.key} · {item.label}
            </button>
          ))}
        </div>
        {variant === "E" &&
        (destination === "Overview" || destination === "Data") ? (
          <ProjectLifecyclePrototype
            destination={destination}
            onNavigate={chooseDestination}
          />
        ) : destination === "Data" ? (
          <>
            <div className={styles.workspaceHeading}>
              <div>
                <h1>Data</h1>
                <p>
                  Project inputs, reusable definitions, and their execution
                  history.
                </p>
              </div>
            </div>
            {variant === "D" || variant === "E" ? (
              <div className={styles.variantD}>
                <aside
                  className={styles.navigator}
                  aria-label="Data collections"
                >
                  <div className={styles.collectionSwitcher}>
                    {operationCollections.map((item) => (
                      <button
                        key={item}
                        type="button"
                        aria-current={collection === item ? "page" : undefined}
                        onClick={() => chooseCollection(item)}
                      >
                        {item}
                        <span>{primaryRecords[item].length}</span>
                      </button>
                    ))}
                  </div>
                  <div className={styles.recordList}>
                    {primaryRecords[
                      collection === "Operations" ? "Operations" : "Datasets"
                    ].map((key) => (
                      <RecordButton
                        key={key}
                        recordKey={key}
                        selected={selected === key}
                        onOpen={openRecord}
                      />
                    ))}
                  </div>
                  <p className={styles.navigatorNote}>
                    Definitions share one place here. Their Runs and outputs
                    remain separate records.
                  </p>
                </aside>
                {selected === "transform" || selected === "batch" ? (
                  <OperationDetail
                    operation={selected}
                    defaults={previewDefaults[selected]}
                    onDefaults={(next) =>
                      setPreviewDefaults((current) => ({
                        ...current,
                        [selected]: next,
                      }))
                    }
                    onOpen={openRecord}
                    onBack={() => setMobileDetail(false)}
                  />
                ) : (
                  <Detail
                    keyName={selected}
                    current={current}
                    inspectingFlow={inspectingFlow}
                    onFlow={() => setInspectingFlow(true)}
                    onCloseFlow={() => setInspectingFlow(false)}
                    onOpen={openRecord}
                    onBack={() => setMobileDetail(false)}
                  />
                )}
              </div>
            ) : null}
            {variant === "A" ? (
              <div className={styles.variantA}>
                <aside
                  className={styles.navigator}
                  aria-label="Data collections"
                >
                  <div className={styles.collectionSwitcher}>
                    {collections.map((item) => (
                      <button
                        key={item}
                        type="button"
                        aria-current={collection === item ? "page" : undefined}
                        onClick={() => chooseCollection(item)}
                      >
                        {item}
                        <span>{primaryRecords[item].length}</span>
                      </button>
                    ))}
                  </div>
                  <div className={styles.recordList}>
                    {primaryRecords[collection].map((key) => (
                      <RecordButton
                        key={key}
                        recordKey={key}
                        selected={selected === key}
                        onOpen={openRecord}
                      />
                    ))}
                  </div>
                </aside>
                <Detail
                  keyName={selected}
                  current={current}
                  inspectingFlow={inspectingFlow}
                  onFlow={() => setInspectingFlow(true)}
                  onCloseFlow={() => setInspectingFlow(false)}
                  onOpen={openRecord}
                  onBack={() => setMobileDetail(false)}
                />
              </div>
            ) : null}
            {variant === "B" ? (
              <div className={styles.variantB}>
                <aside className={styles.navigator} aria-label="Data outline">
                  {collections.map((item) => (
                    <div className={styles.outlineGroup} key={item}>
                      <button
                        className={styles.outlineHeading}
                        type="button"
                        onClick={() => chooseCollection(item)}
                        aria-expanded={collection === item}
                      >
                        {item}
                        <span>{primaryRecords[item].length}</span>
                      </button>
                      {collection === item ? (
                        <div className={styles.outlineChildren}>
                          {primaryRecords[item].map((key) => (
                            <div key={key}>
                              <RecordButton
                                recordKey={key}
                                selected={selected === key}
                                onOpen={openRecord}
                              />
                              {linked[key]?.keys.map((child) => (
                                <RecordButton
                                  key={child}
                                  recordKey={child}
                                  selected={selected === child}
                                  onOpen={openRecord}
                                  compact
                                />
                              ))}
                              {key === "batch" ? (
                                <RecordButton
                                  recordKey="result"
                                  selected={selected === "result"}
                                  onOpen={openRecord}
                                  compact
                                />
                              ) : null}
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </aside>
                <Detail
                  keyName={selected}
                  current={current}
                  inspectingFlow={inspectingFlow}
                  onFlow={() => setInspectingFlow(true)}
                  onCloseFlow={() => setInspectingFlow(false)}
                  onOpen={openRecord}
                  onBack={() => setMobileDetail(false)}
                />
              </div>
            ) : null}
            {variant === "C" ? (
              <div className={styles.variantC}>
                <div className={styles.overview} aria-label="Data overview">
                  {collections.map((item) => (
                    <section key={item} className={styles.overviewSection}>
                      <div className={styles.overviewHeading}>
                        <h2>{item}</h2>
                        <span>
                          {primaryRecords[item].length} in this Project
                        </span>
                      </div>
                      {primaryRecords[item].map((key) => (
                        <RecordButton
                          key={key}
                          recordKey={key}
                          selected={selected === key}
                          onOpen={openRecord}
                        />
                      ))}
                    </section>
                  ))}
                </div>
                <Detail
                  keyName={selected}
                  current={current}
                  inspectingFlow={inspectingFlow}
                  onFlow={() => setInspectingFlow(true)}
                  onCloseFlow={() => setInspectingFlow(false)}
                  onOpen={openRecord}
                  onBack={() => setMobileDetail(false)}
                />
              </div>
            ) : null}
          </>
        ) : destination === "Work" ? (
          <>
            <div className={styles.workspaceHeading}>
              <div>
                <h1>Work</h1>
                <p>
                  Project Artifacts and Files remain distinct from operational
                  Data.
                </p>
              </div>
            </div>
            <div className={styles.variantA}>
              <aside className={styles.navigator} aria-label="Work items">
                <RecordButton
                  recordKey="artifact"
                  selected={selected === "artifact"}
                  onOpen={openRecord}
                />
              </aside>
              <Detail
                keyName="artifact"
                current={records.artifact}
                inspectingFlow={inspectingFlow}
                onFlow={() => setInspectingFlow(true)}
                onCloseFlow={() => setInspectingFlow(false)}
                onOpen={openRecord}
                onBack={() => setMobileDetail(false)}
              />
            </div>
          </>
        ) : (
          <section className={styles.otherDestination}>
            <h1>{destination}</h1>
            <p>
              This destination stays separate from Data in the proposed Project
              explorer.
            </p>
            <button type="button" onClick={() => chooseDestination("Data")}>
              Go to Data
            </button>
          </section>
        )}
      </section>
    </main>
  );
}

function OperationDetail({
  operation,
  defaults,
  onDefaults,
  onOpen,
  onBack,
}: {
  operation: OperationKey;
  defaults: PreviewDefaults;
  onDefaults: (next: PreviewDefaults) => void;
  onOpen: (key: RecordKey) => void;
  onBack: () => void;
}) {
  const [showFlow, setShowFlow] = useState(false);
  const record = records[operation];
  const preview = sampleValues[defaults.source]
    .filter((item) => defaults.filter === "all" || item.load >= 9)
    .sort((left, right) =>
      defaults.sort === "load"
        ? right.load - left.load ||
          left.sourceKey.localeCompare(right.sourceKey)
        : left.sourceKey.localeCompare(right.sourceKey),
    )
    .slice(0, defaults.limit === "2" ? 2 : undefined);
  const run = operation === "transform" ? "transformRun" : "batchRun";

  function update<K extends keyof PreviewDefaults>(
    key: K,
    value: PreviewDefaults[K],
  ) {
    onDefaults({ ...defaults, [key]: value });
  }

  return (
    <section className={styles.detail} aria-label="Selected Data record">
      <button className={styles.mobileBack} type="button" onClick={onBack}>
        Back to Data
      </button>
      <div className={styles.detailHead}>
        <div>
          <span className={styles.kind}>{record.kind}</span>
          <h2>{record.name}</h2>
          <p>{record.detail}</p>
        </div>
        <button
          type="button"
          onClick={() => setShowFlow((current) => !current)}
        >
          {showFlow ? "Close dataflow" : "Inspect dataflow"}
        </button>
      </div>
      {showFlow ? (
        <div className={styles.dataflow}>
          <h3>Dataflow</h3>
          <p>
            Read-only lineage for the saved operation and its completed Run.
            Preview settings do not change these edges.
          </p>
          <ol>
            <li>
              <button
                type="button"
                onClick={() =>
                  onOpen(operation === "batch" ? "dataset" : "result")
                }
              >
                {operation === "batch"
                  ? records.dataset.name
                  : records.result.name}
              </button>
              <span>→ captured input →</span>
              <button type="button" onClick={() => onOpen(run)}>
                {records[run].name}
              </button>
            </li>
            {operation === "batch" ? (
              <li>
                <button type="button" onClick={() => onOpen(run)}>
                  {records[run].name}
                </button>
                <span>→ per-record outcomes →</span>
                <button type="button" onClick={() => onOpen("result")}>
                  {records.result.name}
                </button>
              </li>
            ) : null}
          </ol>
        </div>
      ) : (
        <>
          <div className={styles.operationSummary}>
            <div>
              <strong>Target</strong>
              <span>
                {operation === "transform"
                  ? "Python Transform"
                  : "reference-calculation · MCP tool"}
              </span>
            </div>
            <div>
              <strong>Last durable Run</strong>
              <button type="button" onClick={() => onOpen(run)}>
                {records[run].name}
              </button>
            </div>
          </div>
          <section className={styles.previewPanel} aria-label="Input preview">
            <div className={styles.previewHeading}>
              <div>
                <h3>Preview inputs</h3>
                <p>
                  These saved defaults help inspect possible input. They do not
                  change a Run or downstream Binding.
                </p>
              </div>
              <span>Illustrative values</span>
            </div>
            <div className={styles.previewControls}>
              <label>
                Source
                <select
                  aria-label="Preview source"
                  value={defaults.source}
                  onChange={(event) =>
                    update("source", event.target.value as PreviewSource)
                  }
                >
                  {Object.entries(sourceNames).map(([key, name]) => (
                    <option key={key} value={key}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Filter
                <select
                  aria-label="Preview filter"
                  value={defaults.filter}
                  onChange={(event) =>
                    update(
                      "filter",
                      event.target.value as PreviewDefaults["filter"],
                    )
                  }
                >
                  <option value="all">All values</option>
                  <option value="high">Load ≥ 9</option>
                </select>
              </label>
              <label>
                Sort
                <select
                  aria-label="Preview sort"
                  value={defaults.sort}
                  onChange={(event) =>
                    update(
                      "sort",
                      event.target.value as PreviewDefaults["sort"],
                    )
                  }
                >
                  <option value="source">Source key</option>
                  <option value="load">Highest load</option>
                </select>
              </label>
              <label>
                Show
                <select
                  aria-label="Preview limit"
                  value={defaults.limit}
                  onChange={(event) =>
                    update(
                      "limit",
                      event.target.value as PreviewDefaults["limit"],
                    )
                  }
                >
                  <option value="2">Top 2</option>
                  <option value="all">All</option>
                </select>
              </label>
            </div>
            <div className={styles.previewOutput} aria-live="polite">
              <strong>{preview.length} preview values</strong>
              <span>
                {preview.length
                  ? preview.map((item) => item.sourceKey).join(", ")
                  : "No values match these defaults."}
              </span>
            </div>
          </section>
          <section
            className={styles.savedFlow}
            aria-label="Saved operation flow"
          >
            <div>
              <h3>Durable execution</h3>
              <p>
                The Run captures its explicitly selected input. Downstream steps
                use their own Bindings and retained outputs.
              </p>
            </div>
            <div className={styles.flowPath}>
              <button
                type="button"
                onClick={() =>
                  onOpen(operation === "batch" ? "dataset" : "result")
                }
              >
                {operation === "batch" ? "Load cases" : "Results for BR-204"}
              </button>
              <span aria-hidden="true">→</span>
              <button type="button" onClick={() => onOpen(run)}>
                {records[run].name}
              </button>
              {operation === "batch" ? (
                <>
                  <span aria-hidden="true">→</span>
                  <button type="button" onClick={() => onOpen("result")}>
                    Result Set
                  </button>
                </>
              ) : null}
            </div>
          </section>
          <div className={styles.related}>
            <h3>Runs and results</h3>
            <RecordButton recordKey={run} selected={false} onOpen={onOpen} />
            {operation === "batch" ? (
              <RecordButton
                recordKey="result"
                selected={false}
                onOpen={onOpen}
              />
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}

function RecordButton({
  recordKey,
  selected,
  onOpen,
  compact = false,
}: {
  recordKey: RecordKey;
  selected: boolean;
  onOpen: (key: RecordKey) => void;
  compact?: boolean;
}) {
  const record = records[recordKey];
  return (
    <button
      type="button"
      className={`${styles.recordButton} ${compact ? styles.compactRecord : ""}`}
      aria-current={selected ? "true" : undefined}
      onClick={() => onOpen(recordKey)}
    >
      <strong>{record.name}</strong>
      <small>
        {record.kind} · {record.detail}
      </small>
    </button>
  );
}

function Detail({
  keyName,
  current,
  inspectingFlow,
  onFlow,
  onCloseFlow,
  onOpen,
  onBack,
}: {
  keyName: RecordKey | null;
  current: (typeof records)[RecordKey] | null;
  inspectingFlow: boolean;
  onFlow: () => void;
  onCloseFlow: () => void;
  onOpen: (key: RecordKey) => void;
  onBack: () => void;
}) {
  if (!keyName || !current)
    return (
      <section className={styles.detail}>
        <h2>Select a record</h2>
      </section>
    );
  return (
    <section className={styles.detail} aria-label="Selected Data record">
      <button className={styles.mobileBack} type="button" onClick={onBack}>
        Back to Data
      </button>
      <div className={styles.detailHead}>
        <div>
          <span className={styles.kind}>{current.kind}</span>
          <h2>{current.name}</h2>
          <p>{current.detail}</p>
        </div>
        <button type="button" onClick={inspectingFlow ? onCloseFlow : onFlow}>
          {inspectingFlow ? "Close dataflow" : "Inspect dataflow"}
        </button>
      </div>
      {inspectingFlow ? (
        <Dataflow selected={keyName} onOpen={onOpen} />
      ) : (
        <>
          {keyName === "dataset" ? (
            <div className={styles.facts}>
              <div>
                <strong>128</strong>
                <span>ordered Dataset Records</span>
              </div>
              <div>
                <strong>2</strong>
                <span>definitions use this input</span>
              </div>
            </div>
          ) : null}
          {keyName === "transform" ? (
            <p className={styles.explanation}>
              Declared inputs and output schema are saved with the Definition.
              Previews and durable Runs use the same host-side runner.
            </p>
          ) : null}
          {keyName === "batch" ? (
            <p className={styles.explanation}>
              Reusable mapping from Dataset Records to one approved target. Each
              Run captures its own immutable input and target snapshot.
            </p>
          ) : null}
          {keyName === "batchRun" || keyName === "transformRun" ? (
            <p className={styles.explanation}>
              Completed Run · retained for inspection · never archived
              automatically.
            </p>
          ) : null}
          {keyName === "result" ? (
            <div className={styles.facts}>
              <div>
                <strong>126</strong>
                <span>succeeded</span>
              </div>
              <div>
                <strong>2</strong>
                <span>failed</span>
              </div>
            </div>
          ) : null}
          {linked[keyName] ? (
            <div className={styles.related}>
              <h3>{linked[keyName].title}</h3>
              {linked[keyName].keys.map((key) => (
                <RecordButton
                  key={key}
                  recordKey={key}
                  selected={false}
                  onOpen={onOpen}
                />
              ))}
            </div>
          ) : null}
          {keyName === "dataset" ? (
            <div className={styles.related}>
              <h3>Used by</h3>
              <RecordButton
                recordKey="transform"
                selected={false}
                onOpen={onOpen}
              />
              <RecordButton
                recordKey="batch"
                selected={false}
                onOpen={onOpen}
              />
            </div>
          ) : null}
          {keyName === "result" ? (
            <div className={styles.related}>
              <h3>Produced by</h3>
              <RecordButton
                recordKey="batchRun"
                selected={false}
                onOpen={onOpen}
              />
              <h3>Curated into</h3>
              <RecordButton
                recordKey="artifact"
                selected={false}
                onOpen={onOpen}
              />
            </div>
          ) : null}
          {keyName === "artifact" ? (
            <div className={styles.related}>
              <h3>Source of this Artifact</h3>
              <RecordButton
                recordKey="result"
                selected={false}
                onOpen={onOpen}
              />
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

function Dataflow({
  selected,
  onOpen,
}: {
  selected: RecordKey;
  onOpen: (key: RecordKey) => void;
}) {
  const edges: { from: RecordKey; to: RecordKey; type: string }[] = [
    { from: "result", to: "transformRun", type: "captured input" },
    { from: "transform", to: "transformRun", type: "definition used" },
    { from: "dataset", to: "batch", type: "collection input" },
    { from: "batch", to: "batchRun", type: "one execution" },
    { from: "batchRun", to: "result", type: "per-record outcomes" },
    { from: "result", to: "artifact", type: "one curated Artifact" },
  ];
  return (
    <div className={styles.dataflow}>
      <h3>Dataflow</h3>
      <p>
        Read-only provenance and binding view for {records[selected].name}.
        Select a record to inspect it.
      </p>
      <ol>
        {edges
          .filter((edge) => edge.from === selected || edge.to === selected)
          .map((edge) => (
            <li key={`${edge.from}-${edge.to}`}>
              <button type="button" onClick={() => onOpen(edge.from)}>
                {records[edge.from].name}
              </button>
              <span>→ {edge.type} →</span>
              <button type="button" onClick={() => onOpen(edge.to)}>
                {records[edge.to].name}
              </button>
            </li>
          ))}
      </ol>
    </div>
  );
}
