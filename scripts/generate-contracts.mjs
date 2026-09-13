import { execFileSync } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { compileFromFile } from "json-schema-to-typescript";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const schema = resolve(root, "packages/contracts/schema/contracts.schema.json");
const targets = {
  python: resolve(root, "apps/api/src/agent_hub_api/contracts.py"),
  typescript: resolve(root, "apps/web/src/contracts.ts"),
};

const mode = process.argv[2];
if (mode !== "--write" && mode !== "--check") {
  throw new Error("Usage: node scripts/generate-contracts.mjs --write|--check");
}

const typescript = await compileFromFile(schema, {
  bannerComment: "/* Generated from packages/contracts/schema/contracts.schema.json. Do not edit. */",
  style: { semi: true, singleQuote: false, trailingComma: "all" },
});

const python = execFileSync(
  "uv",
  [
    "run",
    "datamodel-codegen",
    "--input",
    schema,
    "--input-file-type",
    "jsonschema",
    "--output-model-type",
    "pydantic_v2.BaseModel",
    "--target-python-version",
    "3.12",
    "--use-standard-collections",
    "--use-union-operator",
    "--use-annotated",
    "--disable-timestamp",
    "--snake-case-field",
    "--formatters",
    "ruff-check",
    "ruff-format",
  ],
  { cwd: root, encoding: "utf8" },
);

const generated = { [targets.python]: python, [targets.typescript]: typescript };

for (const [target, content] of Object.entries(generated)) {
  if (mode === "--write") {
    await mkdir(dirname(target), { recursive: true });
    await writeFile(target, content);
    continue;
  }

  let existing;
  try {
    existing = await readFile(target, "utf8");
  } catch {
    existing = undefined;
  }

  if (existing !== content) {
    console.error(`Generated contract is stale: ${target}`);
    process.exitCode = 1;
  }
}
