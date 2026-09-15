import assert from "node:assert/strict";
import test from "node:test";

import { parseProjectFileLinks } from "./_project-links";

test("parses safe Project file links without treating other links as files", () => {
  assert.deepEqual(
    parseProjectFileLinks(
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
  assert.deepEqual(parseProjectFileLinks(text), [{ text }]);
});
