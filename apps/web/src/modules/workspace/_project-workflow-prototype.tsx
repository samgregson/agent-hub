"use client";

import { useState } from "react";

import styles from "./project-workflow-prototype.module.css";

type StepKey = "inputs" | "check" | "filter" | "size" | "note";
type RunNumber = 1 | 2;

const steps: {
  key: StepKey;
  title: string;
  method: string;
  from: string;
  to: string;
}[] = [
  {
    key: "inputs",
    title: "Beam schedule",
    method: "Dataset",
    from: "Project source",
    to: "3 beam records",
  },
  {
    key: "check",
    title: "Check imposed-load deflection",
    method: "MCP tool · per beam",
    from: "Beam schedule",
    to: "Result Set",
  },
  {
    key: "filter",
    title: "Isolate failed checks",
    method: "Transform",
    from: "Result Set",
    to: "Selected failures",
  },
  {
    key: "size",
    title: "Size the selected failure",
    method: "MCP tool · Binding",
    from: "Selected failure",
    to: "Sizing result",
  },
  {
    key: "note",
    title: "Draft review note",
    method: "MCP tool · Binding",
    from: "Sizing result",
    to: "Review note",
  },
];

const outcomes: Record<RunNumber, Record<StepKey, string>> = {
  1: {
    inputs: "B-12 uses trial I = 40 × 10⁶ mm⁴. B-13 and B-14 are unchanged.",
    check: "3 checked · B-12 fails this check · 0 tool errors",
    filter: "B-12 selected; B-13 and B-14 excluded.",
    size: "B-12 requires about 43.393 × 10⁶ mm⁴ for this deflection check.",
    note: "A review note for B-12 was explicitly saved as an Artifact.",
  },
  2: {
    inputs:
      "B-12 uses revised trial I = 80 × 10⁶ mm⁴. B-13 and B-14 are unchanged.",
    check: "3 checked · all pass this check · 0 tool errors",
    filter: "Valid empty selection; no failed checks.",
    size: "Skipped because no failed check was selected.",
    note: "Skipped. No new review note or Artifact was created.",
  },
};

const recordsByStep: Record<StepKey, string> = {
  inputs: "Load cases · Dataset",
  check: "Batch Run and Result Set",
  filter: "Transform Run",
  size: "Sizing result · retained MCP output",
  note: "Review note · explicitly saved Artifact",
};

export function ProjectWorkflowPrototype() {
  const [trialI, setTrialI] = useState<"40" | "80">("40");
  const [latestRun, setLatestRun] = useState<RunNumber>(1);
  const [viewedRun, setViewedRun] = useState<RunNumber>(1);
  const [selectedStep, setSelectedStep] = useState<StepKey>("check");
  const [detailOpen, setDetailOpen] = useState(false);
  const [showRecord, setShowRecord] = useState(false);
  const selected = steps.find((step) => step.key === selectedStep)!;
  const isRevised = viewedRun === 2;
  const recordLabel =
    selectedStep === "check"
      ? `BR-${isRevised ? "205" : "204"} · ${recordsByStep.check}`
      : selectedStep === "filter"
        ? `TR-${isRevised ? "104" : "103"} · ${recordsByStep.filter}`
        : recordsByStep[selectedStep];

  function runRevisedWorkflow() {
    if (trialI !== "80" || latestRun === 2) return;
    setLatestRun(2);
    setViewedRun(2);
    setSelectedStep("check");
    setDetailOpen(false);
  }

  function openStep(key: StepKey) {
    setSelectedStep(key);
    setDetailOpen(true);
    setShowRecord(false);
  }

  return (
    <div
      className={`${styles.workflow} ${detailOpen ? styles.detailOpen : ""}`}
    >
      <div className={styles.overviewHeader}>
        <div>
          <h1>Review floor-beam deflection</h1>
          <p>
            Follow the beam schedule through checks, selected failures, sizing,
            and the review note.
          </p>
        </div>
        <span className={styles.workflowType}>
          Project Workflow · illustrative
        </span>
      </div>

      <div className={styles.runBanner}>
        <div>
          <strong>Workflow Run {viewedRun}</strong>
          <span>
            {isRevised
              ? "3 checked · 0 fail this check · no tool errors"
              : "3 checked · 1 fails this check · no tool errors"}
          </span>
        </div>
        <span className={styles.runState}>Completed</span>
      </div>
      {isRevised ? (
        <p className={styles.comparison}>
          Since Run 1: B-12 trial I changed from 40 to 80 × 10⁶ mm⁴; failed
          checks changed from 1 to 0. Sizing and note steps were skipped.
        </p>
      ) : null}

      <div className={styles.layout}>
        <div className={styles.mainColumn}>
          <section className={styles.stepSection} aria-label="Workflow steps">
            <div className={styles.sectionHeading}>
              <h2>Task flow</h2>
              <p>Select a step to inspect its captured input and outcome.</p>
            </div>
            <ol className={styles.stepList}>
              {steps.map((step, index) => {
                const skipped =
                  isRevised && (step.key === "size" || step.key === "note");
                return (
                  <li key={step.key}>
                    <button
                      type="button"
                      aria-current={
                        selectedStep === step.key ? "step" : undefined
                      }
                      onClick={() => openStep(step.key)}
                    >
                      <span className={styles.stepNumber}>{index + 1}</span>
                      <span className={styles.stepText}>
                        <strong>{step.title}</strong>
                        <small>
                          {step.from} → {step.to}
                        </small>
                      </span>
                      <span className={styles.stepEnd}>
                        <span>{step.method}</span>
                        <strong>{skipped ? "Skipped" : "Completed"}</strong>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </section>

          <section
            className={styles.stepDetail}
            aria-label="Selected workflow step"
          >
            <button
              className={styles.mobileBack}
              type="button"
              onClick={() => setDetailOpen(false)}
            >
              Back to workflow
            </button>
            <div className={styles.sectionHeading}>
              <h2>{selected.title}</h2>
              <span>{selected.method}</span>
            </div>
            <p className={styles.outcome}>
              {outcomes[viewedRun][selectedStep]}
            </p>
            <dl className={styles.lineage}>
              <div>
                <dt>Captured from</dt>
                <dd>{selected.from}</dd>
              </div>
              <div>
                <dt>Produced</dt>
                <dd>{selected.to}</dd>
              </div>
              <div>
                <dt>Record</dt>
                <dd>{recordLabel}</dd>
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
                <strong>{recordLabel}</strong>
                <p>{outcomes[viewedRun][selectedStep]}</p>
              </div>
            ) : null}
            <p className={styles.detailFoot}>
              This view traces the saved Run. Preview filters do not change the
              chain or its recorded results.
            </p>
          </section>
        </div>

        <aside
          className={styles.sideColumn}
          aria-label="Workflow runs and inputs"
        >
          <section className={styles.inputSection}>
            <h2>Iterate on inputs</h2>
            <p>
              Revise B-12’s trial section and execute the chain again. Earlier
              Runs stay inspectable.
            </p>
            <label>
              B-12 trial I
              <select
                value={trialI}
                onChange={(event) =>
                  setTrialI(event.target.value as "40" | "80")
                }
              >
                <option value="40">40 × 10⁶ mm⁴ · original</option>
                <option value="80">80 × 10⁶ mm⁴ · revised</option>
              </select>
            </label>
            <button
              className={styles.runButton}
              type="button"
              disabled={trialI !== "80" || latestRun === 2}
              onClick={runRevisedWorkflow}
            >
              {latestRun === 2 ? "Revised Run created" : "Run revised workflow"}
            </button>
            <small>
              Prototype action. An agent-proposed input change and Run would
              pause for approval.
            </small>
          </section>

          <section className={styles.historySection}>
            <h2>Run history</h2>
            <button
              type="button"
              aria-current={viewedRun === 1 ? "true" : undefined}
              onClick={() => {
                setViewedRun(1);
                setDetailOpen(false);
              }}
            >
              <strong>Run 1 · original input</strong>
              <span>1 fails this check</span>
            </button>
            {latestRun === 2 ? (
              <button
                type="button"
                aria-current={viewedRun === 2 ? "true" : undefined}
                onClick={() => {
                  setViewedRun(2);
                  setDetailOpen(false);
                }}
              >
                <strong>Run 2 · revised B-12</strong>
                <span>All pass this check</span>
              </button>
            ) : null}
          </section>
          <p className={styles.scopeNote}>
            Passing this imposed-load deflection check is not a whole-beam
            safety or code-compliance verdict.
          </p>
        </aside>
      </div>
    </div>
  );
}
