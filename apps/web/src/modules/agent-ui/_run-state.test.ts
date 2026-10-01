import assert from "node:assert/strict";
import test from "node:test";

import { shouldClearTransientRunError } from "./_run-state";

test("a durable successful run clears a prior transient chat error", () => {
  assert.equal(shouldClearTransientRunError("succeeded"), true);
});

test("a non-successful or unknown run does not clear a transient chat error", () => {
  assert.equal(shouldClearTransientRunError("failed"), false);
  assert.equal(shouldClearTransientRunError(undefined), false);
});
