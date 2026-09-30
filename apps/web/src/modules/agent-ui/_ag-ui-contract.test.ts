import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import assert from "node:assert/strict";
import test from "node:test";

import { EventSchemas, RunAgentInputSchema } from "@ag-ui/core";

test("pinned AG-UI fixture matches the browser contract", () => {
  const fixturePath = resolve(
    __dirname,
    "../../../../../packages/contracts/fixtures/ag-ui-0.0.59.json",
  );
  const fixture = JSON.parse(readFileSync(fixturePath, "utf8")) as {
    events: unknown[];
    resumeInput: unknown;
  };

  const events = fixture.events.map((event) => EventSchemas.parse(event));
  const resumeInput = RunAgentInputSchema.parse(fixture.resumeInput);

  assert.equal(events.length, 9);
  assert.equal(resumeInput.resume?.[0]?.interruptId, "interrupt-fixture");
});
