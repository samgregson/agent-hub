import assert from "node:assert/strict";
import test from "node:test";

import { findDependencyCycle } from "./module-import-graph.mjs";

test("allows a layered Module dependency graph", () => {
  assert.equal(
    findDependencyCycle(
      new Map([
        ["batch_execution", new Set(["transforms", "input_selection"])],
        ["transforms", new Set(["input_selection"])],
        ["input_selection", new Set()],
      ]),
    ),
    null,
  );
});

test("reports the import loop when a lower Module imports its caller", () => {
  assert.deepEqual(
    findDependencyCycle(
      new Map([
        ["batch_execution", new Set(["transforms"])],
        ["transforms", new Set(["batch_execution"])],
      ]),
    ),
    ["batch_execution", "transforms", "batch_execution"],
  );
});
