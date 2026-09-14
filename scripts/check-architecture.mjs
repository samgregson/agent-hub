import { readFile, readdir } from "node:fs/promises";
import { extname, join, relative, sep } from "node:path";

const root = new URL("../", import.meta.url).pathname;
const webRoot = join(root, "apps/web/src");
const apiRoot = join(root, "apps/api/src/agent_hub_api");
const violations = [];

async function files(directory, extensions) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries.map(async (entry) => {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) return files(path, extensions);
      return extensions.has(extname(entry.name)) ? [path] : [];
    }),
  );
  return nested.flat();
}

function report(path, message) {
  violations.push(`${relative(root, path)}: ${message}`);
}

for (const path of await files(webRoot, new Set([".ts", ".tsx"]))) {
  const source = await readFile(path, "utf8");
  const localPath = relative(webRoot, path).split(sep);
  const moduleName = localPath[0] === "modules" ? localPath[1] : undefined;

  if (moduleName && /from\s+["']@\/app(?:\/|["'])/.test(source)) {
    report(path, "web Modules cannot import from the Next.js composition root");
  }

  for (const match of source.matchAll(
    /from\s+["']@\/modules\/([^/"']+)\/(_[^"']*)["']/g,
  )) {
    if (match[1] !== moduleName) {
      report(path, `imports private implementation from Module '${match[1]}'`);
    }
  }
}

for (const path of await files(apiRoot, new Set([".py"]))) {
  const source = await readFile(path, "utf8");
  const localPath = relative(apiRoot, path).split(sep);
  const moduleName = localPath[0] === "modules" ? localPath[1] : undefined;

  if (moduleName && /(?:from|import)\s+agent_hub_api\.main\b/.test(source)) {
    report(path, "API Modules cannot import from the FastAPI composition root");
  }

  for (const match of source.matchAll(
    /(?:from|import)\s+agent_hub_api\.modules\.([^.\s]+)\.(_[^\s]*)/g,
  )) {
    if (match[1] !== moduleName) {
      report(path, `imports private implementation from Module '${match[1]}'`);
    }
  }
}

if (violations.length) {
  console.error(`Architecture violations:\n${violations.join("\n")}`);
  process.exitCode = 1;
} else {
  console.log("Architecture dependency directions are valid.");
}
