import assert from "node:assert/strict";
import test from "node:test";

import {
  automaticThreadTitle,
  hasProvisionalThreadTitle,
  initialThreadTitle,
} from "./_thread-title";

test("uses an orderly provisional Thread title", () => {
  assert.equal(initialThreadTitle(3), "New Thread 3");
  assert.equal(hasProvisionalThreadTitle("New Thread 3"), true);
  assert.equal(hasProvisionalThreadTitle("Renamed Thread"), false);
});

test("derives a compact deterministic title from the first message", () => {
  assert.equal(
    automaticThreadTitle("  Compare\n  the proposed beam layouts  "),
    "Compare the proposed beam layouts",
  );
  assert.equal(automaticThreadTitle(" \n "), null);
  assert.equal(automaticThreadTitle("x".repeat(61)), `${"x".repeat(59)}…`);
});
