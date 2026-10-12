import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { copyFile, mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";

const scriptDirectory = dirname(new URL(import.meta.url).pathname);

test("architecture gate rejects API and web Module import cycles", async () => {
  const fixture = await mkdtemp(join(tmpdir(), "agent-hub-imports-"));
  try {
    await mkdir(join(fixture, "scripts"));
    await mkdir(
      join(fixture, "apps/api/src/agent_hub_api/modules/workflows"),
      {
        recursive: true,
      },
    );
    await mkdir(
      join(fixture, "apps/api/src/agent_hub_api/modules/functions"),
      {
        recursive: true,
      },
    );
    await mkdir(join(fixture, "apps/api/src/agent_hub_api/modules/datasets"), {
      recursive: true,
    });
    await mkdir(join(fixture, "apps/web/src/modules/first"), {
      recursive: true,
    });
    await mkdir(join(fixture, "apps/web/src/modules/second"), {
      recursive: true,
    });
    await copyFile(
      join(scriptDirectory, "check-architecture.mjs"),
      join(fixture, "scripts/check-architecture.mjs"),
    );
    await copyFile(
      join(scriptDirectory, "module-import-graph.mjs"),
      join(fixture, "scripts/module-import-graph.mjs"),
    );
    await writeFile(
      join(
        fixture,
        "apps/api/src/agent_hub_api/modules/workflows/_application.py",
      ),
      "from agent_hub_api.modules.functions import FunctionModule\n",
    );
    await writeFile(
      join(
        fixture,
        "apps/api/src/agent_hub_api/modules/functions/_application.py",
      ),
      "from agent_hub_api.modules.workflows import WorkflowModule\n",
    );
    await writeFile(
      join(
        fixture,
        "apps/api/src/agent_hub_api/modules/functions/_private_import.py",
      ),
      "from agent_hub_api.modules.datasets._application import Dataset\n",
    );
    await writeFile(
      join(fixture, "apps/web/src/modules/first/index.ts"),
      'import { second } from "@/modules/second";\n',
    );
    await writeFile(
      join(fixture, "apps/web/src/modules/second/index.ts"),
      'import { first } from "@/modules/first";\n',
    );

    let diagnostics = "";
    assert.throws(
      () =>
        execFileSync(
          process.execPath,
          [join(fixture, "scripts/check-architecture.mjs")],
          {
            encoding: "utf8",
            stdio: "pipe",
          },
        ),
      (error) => {
        diagnostics = [
          String(error.stdout),
          String(error.stderr),
          String(error.message),
        ].join("\n");
        return true;
      },
    );
    assert.match(
      diagnostics,
      /API Module import cycle:.*(?:functions.*workflows|workflows.*functions)/,
    );
    assert.match(diagnostics, /web Module import cycle:.*first.*second/);
    assert.match(
      diagnostics,
      /imports private implementation of Module 'datasets'/,
    );
  } finally {
    await rm(fixture, { recursive: true, force: true });
  }
});
