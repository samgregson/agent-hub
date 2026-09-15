import assert from "node:assert/strict";
import test from "node:test";

import { parseVirtualFileLinks } from "./_project-links";

test("parses safe Project file links without treating other links as files", () => {
  assert.deepEqual(
    parseVirtualFileLinks(
      "Open [the check](/project/calcs/check.md), not [docs](https://example.com).",
    ),
    [
      { text: "Open " },
      { label: "the check", path: "/project/calcs/check.md" },
      { text: ", not [docs](https://example.com)." },
    ],
  );
});

test("does not activate a Project traversal link", () => {
  const text = "[host file](/project/../etc/passwd)";
  assert.deepEqual(parseVirtualFileLinks(text), [{ text }]);
});

test("parses Thread-local scratch file links without activating other paths", () => {
  assert.deepEqual(
    parseVirtualFileLinks(
      "Open [working notes](/scratch/notes.md), not /scratch/no-link.md.",
    ),
    [
      { text: "Open " },
      { label: "working notes", path: "/scratch/notes.md" },
      { text: ", not /scratch/no-link.md." },
    ],
  );
});
