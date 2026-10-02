"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import styles from "./project-explorer-prototype.module.css";

// Throwaway issue #37 prototype: compare three navigation structures using the
// same illustrative Project records. Nothing here reads or writes Project data.
type Variant = "A" | "B" | "C";
type Destination = "Chats" | "Work" | "Data" | "Sources" | "Plugins";
type Collection = "Datasets" | "Transform Definitions" | "Batch Definitions";
type RecordKey =
  | "dataset"
  | "transform"
  | "transformRun"
  | "batch"
  | "batchRun"
  | "result"
  | "artifact";

const variants: { key: Variant; label: string }[] = [
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
const collections: Collection[] = [
  "Datasets",
  "Transform Definitions",
  "Batch Definitions",
];

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
  if (typeof window === "undefined") return "A";
  const value = new URLSearchParams(window.location.search).get("variant");
  return value === "B" || value === "C" ? value : "A";
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
    () => "A",
  );
  const [destination, setDestination] = useState<Destination>("Data");
  const [collection, setCollection] = useState<Collection>("Datasets");
  const [selected, setSelected] = useState<RecordKey | null>("dataset");
  const [inspectingFlow, setInspectingFlow] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [mobileDetail, setMobileDetail] = useState(false);

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

  function chooseVariant(next: Variant) {
    const url = new URL(window.location.href);
    url.searchParams.set("variant", next);
    window.history.replaceState(null, "", url);
    window.dispatchEvent(new Event("prototype-variant-changed"));
    setDrawerOpen(false);
  }

  function cycle(delta: number) {
    const index = variants.findIndex((item) => item.key === variant);
    chooseVariant(
      variants[(index + delta + variants.length) % variants.length].key,
    );
  }

  function chooseDestination(next: Destination) {
    setDestination(next);
    if (next === "Work") setSelected("artifact");
    if (next === "Data" && selected === "artifact")
      setSelected(primaryRecords[collection][0]);
    setDrawerOpen(false);
    setMobileDetail(false);
    setInspectingFlow(false);
  }

  function chooseCollection(next: Collection) {
    setDestination("Data");
    setCollection(next);
    setSelected(primaryRecords[next][0]);
    setInspectingFlow(false);
    setMobileDetail(false);
  }

  function openRecord(key: RecordKey) {
    setDestination(key === "artifact" ? "Work" : "Data");
    if (key !== "artifact") setCollection(collectionOf[key]);
    setSelected(key);
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
        {destinations.map((item) => (
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
              {destinations.map((item) => (
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
            {destination === "Data" ? (
              <div className={styles.drawerCollections}>
                {collections.map((item) => (
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
        {destination === "Data" ? (
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

      {process.env.NODE_ENV !== "production" ? (
        <div className={styles.variantBar} aria-label="Prototype variants">
          <button
            type="button"
            onClick={() => cycle(-1)}
            aria-label="Previous variant"
          >
            ←
          </button>
          <span>
            {variant} · {variants.find((item) => item.key === variant)?.label}
          </span>
          <button
            type="button"
            onClick={() => cycle(1)}
            aria-label="Next variant"
          >
            →
          </button>
        </div>
      ) : null}
    </main>
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
    { from: "dataset", to: "transform", type: "collection input" },
    { from: "transform", to: "transformRun", type: "one execution" },
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
        {edges.map((edge) => (
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
