import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { checkPluginBoundaries } from "./check-plugin-boundaries.mjs";

test("rejects Plugin imports in both directions and between Plugins", async () => {
  const root = await mkdtemp(join(tmpdir(), "plugin-boundary-"));
  async function file(path, source) {
    await mkdir(dirname(join(root, path)), { recursive: true });
    await writeFile(join(root, path), source);
  }
  try {
    await file("apps/web/package.json", '{"name":"@agent-hub/web"}');
    await file("plugins/first/app/package.json", '{"name":"first-app"}');
    await file("plugins/first/src/first/__init__.py", "");
    await file("plugins/second/src/second/__init__.py", "");
    await file("apps/api/src/agent_hub_api/__init__.py", "");
    await file(
      "plugins/first/app/a.ts",
      'import "../../../apps/web/src/a"; export * from "../../second/app/a"; import("@/modules/a");',
    );
    await file("apps/web/src/a.ts", 'const plugin = require("first-app");');
    await file(
      "plugins/first/src/first/a.py",
      "from agent_hub_api import module\nimport second\n",
    );
    await file(
      "apps/api/src/agent_hub_api/a.py",
      'import importlib\nimportlib.import_module("first.a")\n',
    );
    const violations = await checkPluginBoundaries(root);
    assert.equal(violations.length, 8, violations.join("\n"));
    await file(
      "plugins/first/app/a.ts",
      'import "./local"; import React from "react"; // import "@/modules/a"\nconst text = "import first-app";',
    );
    await file("apps/web/src/a.ts", "");
    await file(
      "plugins/first/src/first/a.py",
      "from . import local\nimport json\n# import second\n",
    );
    await file("apps/api/src/agent_hub_api/a.py", 'text = "import first"\n');
    assert.deepEqual(await checkPluginBoundaries(root), []);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("rejects resolved TypeScript aliases and local package dependencies", async () => {
  const root = await mkdtemp(join(tmpdir(), "plugin-alias-"));
  async function file(path, source) {
    await mkdir(dirname(join(root, path)), { recursive: true });
    await writeFile(join(root, path), source);
  }
  try {
    await file("apps/web/src/internal.ts", "export const value = 1;");
    await file(
      "plugins/first/app/tsconfig.json",
      JSON.stringify({
        compilerOptions: { paths: { "host/*": ["../../../apps/web/src/*"] } },
      }),
    );
    await file(
      "plugins/first/app/main.ts",
      'export { value } from "host/internal";',
    );
    await file(
      "plugins/first/app/package.json",
      '{"name":"first-app","dependencies":{"second-app":"file:../../second/app"}}',
    );
    await file("plugins/second/app/package.json", '{"name":"second-app"}');
    const violations = await checkPluginBoundaries(root);
    assert(violations.some((message) => message.includes("host/internal")));
    assert(violations.some((message) => message.includes("second-app")));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("rejects computed imports that conceal boundary targets", async () => {
  const root = await mkdtemp(join(tmpdir(), "plugin-computed-"));
  try {
    await mkdir(join(root, "plugins/first/app"), { recursive: true });
    await writeFile(
      join(root, "plugins/first/app/main.ts"),
      "const name = 'host'; import(name);",
    );
    await writeFile(
      join(root, "plugins/first/app/main.py"),
      "from importlib import import_module as load\nname = 'host'\nload(name)\n",
    );
    const violations = await checkPluginBoundaries(root);
    assert.equal(
      violations.filter((message) => message.includes("computed imports"))
        .length,
      2,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
