import assert from "node:assert/strict";
import test from "node:test";
import type { MetadataRow } from "./metadata";
import {
  assignMetadata,
  colourMap,
  readView,
  scaleLegend,
  valueKey,
} from "./metadata";

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
  assert.throws(() =>
    readView({
      ...view,
      colourScale: {
        key: "x",
        bands: [{ max: 1, colour: "red" }],
        aboveColour: "#ff0000",
      },
    }),
  );
});

test("numeric scale uses inclusive boundaries and leaves missing values grey", () => {
  const scale = {
    key: "utilisation",
    bands: [
      { max: 0.95, colour: "#008000" },
      { max: 1, colour: "#ffbf00" },
    ],
    aboveColour: "#ff0000",
  };
  const values = [0.95, 0.951, 1, 1.001, null, undefined];
  const rows = values.map((value, i): MetadataRow => ({
    globalId: String(i),
    values: value === undefined ? {} : { utilisation: value },
  }));
  const colours = colourMap(rows, "utilisation", scale);
  assert.deepEqual(
    values.map((value) => colours.get(valueKey(value))),
    ["#008000", "#ffbf00", "#ffbf00", "#ff0000", "#94a3b8", "#94a3b8"],
  );
});

test("numeric scales work with arbitrary keys and show threshold intervals", () => {
  const scale = {
    key: "temperature",
    bands: [
      { max: -5, colour: "#112233" },
      { max: 20, colour: "#445566" },
    ],
    aboveColour: "#778899",
  };
  const rows: MetadataRow[] = [
    { globalId: "a", values: { temperature: -5 } },
    { globalId: "b", values: { temperature: 21 } },
  ];
  assert.equal(
    colourMap(rows, "temperature", scale).get(valueKey(-5)),
    "#112233",
  );
  assert.equal(
    colourMap(rows, "temperature", scale).get(valueKey(21)),
    "#778899",
  );
  assert.deepEqual(
    [...scaleLegend(scale)],
    [
      ["≤ -5", "#112233"],
      ["> -5 and ≤ 20", "#445566"],
      ["> 20", "#778899"],
      ["Unassigned or nonnumeric", "#94a3b8"],
    ],
  );
});
