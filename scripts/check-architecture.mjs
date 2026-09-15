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

function withoutPythonCommentsAndStrings(source) {
  let result = "";
  let quote;
  let triple = false;
  let comment = false;

  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    const next = source.slice(index, index + 3);

    if (comment) {
      result += character === "\n" ? "\n" : " ";
    } else if (quote) {
      if (triple && next === quote.repeat(3)) {
        result += "   ";
        index += 2;
        quote = undefined;
        triple = false;
      } else if (!triple && character === "\\") {
        result += "  ";
        index += 1;
      } else {
        result += character === "\n" ? "\n" : " ";
        if (!triple && character === quote) quote = undefined;
      }
    } else if (character === "#") {
      result += " ";
      comment = true;
    } else if (character === "'" || character === '"') {
      quote = character;
      triple = next === character.repeat(3);
      result += triple ? "   " : " ";
      if (triple) index += 2;
    } else {
      result += character;
    }

    if (character === "\n") comment = false;
  }

  return result;
}

function checkPythonModulePath(path, moduleName, importedPath) {
  const prefix = "agent_hub_api.modules.";
  if (!importedPath.startsWith(prefix)) return;

  const parts = importedPath.split(".");
  const importedModule = parts[2];
  const subpath = parts.slice(3);
  if (importedModule === moduleName || !subpath.length) return;

  const kind = subpath[0].startsWith("_")
    ? "imports private implementation"
    : "bypasses the package-root Interface";
  report(path, `${kind} of Module '${importedModule}'`);
}

function relativePythonModulePath(moduleName, dots, suffix) {
  const currentPackage = ["agent_hub_api", "modules", moduleName];
  const parentPackage = currentPackage.slice(
    0,
    currentPackage.length - (dots.length - 1),
  );
  return [...parentPackage, ...suffix.split(".").filter(Boolean)].join(".");
}

function checkPythonModuleImports(path, source, moduleName) {
  const code = withoutPythonCommentsAndStrings(source);

  for (const match of code.matchAll(
    /\bfrom\s+(agent_hub_api\.modules\.[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s+import\b/g,
  )) {
    checkPythonModulePath(path, moduleName, match[1]);
  }

  for (const match of code.matchAll(/\bimport\s+([^\n;]+)/g)) {
    for (const importedPath of match[1].split(",")) {
      checkPythonModulePath(
        path,
        moduleName,
        importedPath.trim().split(/\s+as\s+/)[0],
      );
    }
  }

  for (const match of code.matchAll(
    /\bfrom\s+(\.+)([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)?\s+import\b/g,
  )) {
    const importedPath = relativePythonModulePath(
      moduleName,
      match[1],
      match[2] ?? "",
    );
    checkPythonModulePath(path, moduleName, importedPath);
  }
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

  for (const match of source.matchAll(
    /from\s+["']@\/modules\/([^/"']+)\/([^"']+)["']/g,
  )) {
    const [, importedModule, entryPoint] = match;
    if (importedModule !== moduleName && entryPoint !== "server") {
      report(
        path,
        `bypasses the package-root Interface of Module '${importedModule}'`,
      );
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

  if (
    moduleName &&
    !path.endsWith("_http.py") &&
    /from\s+fastapi\s+import[^\n]*\bRequest\b/.test(source)
  ) {
    report(path, "only HTTP adapters may depend on FastAPI Request objects");
  }

  if (moduleName) checkPythonModuleImports(path, source, moduleName);
}

if (violations.length) {
  console.error(`Architecture violations:\n${violations.join("\n")}`);
  process.exitCode = 1;
} else {
  console.log("Architecture dependency directions are valid.");
}
