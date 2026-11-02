import assert from "node:assert/strict";
import test from "node:test";
import type { MetadataRow } from "./metadata";
import { assignMetadata, colourMap, readView, valueKey } from "./metadata";

test("calculation joins preserve scalar types and replace only the selected object's key", () => {
  const rows: MetadataRow[] = [
    { globalId: "beam-a", values: { status: "pass", ratio: 0.5 } },
    { globalId: "beam-b", values: { status: "fail" } },
  ];
  const updated = assignMetadata(rows, "beam-a", "ratio", 0.9);
  assert.deepEqual(updated.find((row) => row.globalId === "beam-a")?.values, {
    status: "pass",
    ratio: 0.9,
  });
  assert.equal(rows[0].values.ratio, 0.5);
  assert.equal(
    updated.find((row) => row.globalId === "beam-b")?.values.status,
    "fail",
  );
  assert.throws(() => assignMetadata(rows, "beam-a", "ratio", Infinity));
});
test("colour categories distinguish numbers, strings, null and missing, and are order independent", () => {
  const rows: MetadataRow[] = [1, "1", null, undefined].map(
    (value, index): MetadataRow => ({
      globalId: String(index),
      values: value === undefined ? {} : { value },
    }),
  );
  const colours = colourMap(rows, "value");
  assert.equal(colours.size, 4);
  assert.equal(colours.get(valueKey(undefined)), "#94a3b8");
  assert.deepEqual(colours, colourMap([...rows].reverse(), "value"));
});
test("direct MCP and saved Artifact results use the same portable view", () => {
  const view = {
    kind: "ifc.view",
    schemaVersion: "1",
    ifcText: "IFC",
    metadata: [],
  };
  assert.equal(readView(view), view);
  assert.equal(readView({ payload: { output: view } }), view);
  assert.throws(() => readView({ kind: "other" }));
  assert.throws(() =>
    readView({ ...view, metadata: [{ globalId: "a", values: { x: {} } }] }),
  );
});
