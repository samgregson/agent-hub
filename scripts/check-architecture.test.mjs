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
      join(fixture, "apps/api/src/agent_hub_api/modules/batch_execution"),
      {
        recursive: true,
      },
    );
    await mkdir(
      join(fixture, "apps/api/src/agent_hub_api/modules/transforms"),
      {
        recursive: true,
      },
    );
    await mkdir(
      join(fixture, "apps/api/src/agent_hub_api/modules/input_selection"),
      {
        recursive: true,
      },
    );
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
        "apps/api/src/agent_hub_api/modules/batch_execution/_application.py",
      ),
      "from agent_hub_api.modules.transforms import TransformModule\n",
    );
    await writeFile(
      join(
        fixture,
        "apps/api/src/agent_hub_api/modules/transforms/_application.py",
      ),
      "from agent_hub_api.modules.batch_execution import BatchExecutionModule\n",
    );
    await writeFile(
      join(
        fixture,
        "apps/api/src/agent_hub_api/modules/input_selection/_selection.py",
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
        assert.match(
          error.stderr,
          /API Module import cycle:.*batch_execution.*transforms/,
        );
        assert.match(error.stderr, /web Module import cycle:.*first.*second/);
        assert.match(
          error.stderr,
          /Input Selection must not import source or execution Modules/,
        );
        assert.match(
          error.stderr,
          /imports private implementation of Module 'datasets'/,
        );
        return true;
      },
    );
  } finally {
    await rm(fixture, { recursive: true, force: true });
  }
});
