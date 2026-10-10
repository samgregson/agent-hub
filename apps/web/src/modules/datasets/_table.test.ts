import assert from "node:assert/strict";
import test from "node:test";

import { filterDatasetRecords, scalarColumns, scalarText } from "./_table.js";

const records = [
  {
    id: "a",
    position: 0,
    sourceKey: "LC-1",
    value: { load: 12.5, active: true, details: { unit: "kN" } },
  },
  {
    id: "b",
    position: 1,
    sourceKey: null,
    value: { name: "Second", load: null, tags: ["trial"] },
  },
  {
    id: "c",
    position: 2,
    sourceKey: "LC-3",
    value: { load: 40, active: false },
  },
];

test("scalar columns follow source order and leave nested values in the full record", () => {
  assert.deepEqual(scalarColumns(records), ["load", "active", "name"]);
  assert.equal(scalarText(records[0].value.details), null);
  assert.equal(scalarText(records[1].value.load), "null");
  assert.equal(scalarText(records[2].value.active), "false");
});

test("view filter searches record keys and scalar values without reordering records", () => {
  const columns = scalarColumns(records);
  assert.deepEqual(
    filterDatasetRecords(records, "lc-", columns).map((record) => record.id),
    ["a", "c"],
  );
  assert.deepEqual(
    filterDatasetRecords(records, "second", columns).map((record) => record.id),
    ["b"],
  );
  assert.deepEqual(
    filterDatasetRecords(records, "40", columns).map((record) => record.id),
    ["c"],
  );
  assert.deepEqual(filterDatasetRecords(records, "trial", columns), []);
  assert.deepEqual(
    filterDatasetRecords(records, " ", columns).map((record) => record.id),
    ["a", "b", "c"],
  );
});
