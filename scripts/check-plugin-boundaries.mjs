import { readFile, readdir } from "node:fs/promises";
import { dirname, extname, join, relative, resolve, sep } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const skipped = new Set([
  "node_modules",
  ".git",
  ".venv",
  ".cache",
  ".next",
  "dist",
  ".test-build",
  "__pycache__",
]);
async function walk(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  return (
    await Promise.all(
      entries
        .filter(
          (entry) =>
            !skipped.has(entry.name) && !entry.name.startsWith(".pytest"),
        )
        .map((entry) => {
          const path = join(directory, entry.name);
          return entry.isDirectory() ? walk(path) : [path];
        }),
    )
  ).flat();
}
function pluginOwner(root, path) {
  const parts = relative(root, path).split(sep);
  return parts[0] === "plugins" ? parts[1] : null;
}
function crosses(root, from, to) {
  const a = pluginOwner(root, from),
    b = pluginOwner(root, to);
  return (a || b) && a !== b;
}
const pythonImports = String.raw`
import ast, json, sys
result = []
for path in json.load(sys.stdin):
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    importers = {"__import__", "importlib.import_module"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib": importers.add((alias.asname or alias.name) + ".import_module")
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module": importers.add(alias.asname or alias.name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend([path, alias.name, 0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            result.append([path, node.module or "", node.level])
            result.extend([path, (node.module + "." if node.module else "") + alias.name, node.level] for alias in node.names)
        elif isinstance(node, ast.Call) and ast.unparse(node.func) in importers:
            value = node.args[0] if node.args else None
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                specifier = value.value
                level = len(specifier) - len(specifier.lstrip("."))
                result.append([path, specifier.lstrip("."), level])
            else:
                result.append([path, None, 0])
print(json.dumps(result))
`;
export async function checkPluginBoundaries(root) {
  root = resolve(root);
  const paths = await walk(root);
  const diagnostics = [];
  const packages = new Map();
  const pythonPackages = new Map();
  for (const path of paths) {
    if (path.endsWith(`${sep}package.json`)) {
      const manifest = JSON.parse(await readFile(path, "utf8"));
      if (manifest.name) packages.set(manifest.name, dirname(path));
    }
    const match = relative(root, path)
      .split(sep)
      .join("/")
      .match(/^(.*?\/src)\/([^/.]+)(?:\/.*)?\.py$/);
    if (match) pythonPackages.set(match[2], join(root, match[1], match[2]));
  }
  function check(from, to, specifier) {
    if (crosses(root, from, to))
      diagnostics.push(
        `${relative(root, from)}: forbidden Plugin boundary import '${specifier}'`,
      );
  }
  for (const path of paths) {
    if (path.endsWith(`${sep}package.json`)) {
      const manifest = JSON.parse(await readFile(path, "utf8"));
      for (const [name, version] of Object.entries({
        ...manifest.dependencies,
        ...manifest.devDependencies,
        ...manifest.peerDependencies,
        ...manifest.optionalDependencies,
      })) {
        if (packages.has(name)) check(path, packages.get(name), name);
        if (/^(?:file|link):/.test(version))
          check(
            path,
            resolve(dirname(path), version.replace(/^(?:file|link):/, "")),
            name,
          );
      }
    }
    if (!/\.(?:[cm]?[jt]sx?)$/.test(path)) continue;
    const source = ts.createSourceFile(
      path,
      await readFile(path, "utf8"),
      ts.ScriptTarget.Latest,
      true,
    );
    const configPath = ts.findConfigFile(dirname(path), ts.sys.fileExists);
    let options = {};
    if (configPath) {
      const config = ts.readConfigFile(configPath, ts.sys.readFile);
      options = ts.parseJsonConfigFileContent(
        config.config,
        ts.sys,
        dirname(configPath),
      ).options;
    }
    function visit(node) {
      let literal;
      if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node))
        literal = node.moduleSpecifier;
      if (
        ts.isImportEqualsDeclaration(node) &&
        ts.isExternalModuleReference(node.moduleReference)
      )
        literal = node.moduleReference.expression;
      if (
        ts.isCallExpression(node) &&
        (node.expression.kind === ts.SyntaxKind.ImportKeyword ||
          (ts.isIdentifier(node.expression) &&
            node.expression.text === "require"))
      ) {
        literal = node.arguments[0];
        if (!literal || !ts.isStringLiteralLike(literal))
          diagnostics.push(
            `${relative(root, path)}: computed imports cannot be checked against Plugin boundaries`,
          );
      }
      if (literal && ts.isStringLiteralLike(literal)) {
        const specifier = literal.text;
        const resolved = ts.resolveModuleName(specifier, path, options, ts.sys)
          .resolvedModule?.resolvedFileName;
        if (resolved && !resolved.includes(`${sep}node_modules${sep}`))
          check(path, resolved, specifier);
        if (specifier.startsWith("."))
          check(path, resolve(dirname(path), specifier), specifier);
        if (specifier.startsWith("/")) check(path, specifier, specifier);
        if (specifier.startsWith("@/"))
          check(
            path,
            join(root, "apps/web/src", specifier.slice(2)),
            specifier,
          );
        for (const [name, target] of packages)
          if (specifier === name || specifier.startsWith(`${name}/`))
            check(path, target, specifier);
      }
      ts.forEachChild(node, visit);
    }
    visit(source);
  }
  const pyPaths = paths.filter((path) => extname(path) === ".py");
  const python = spawnSync(
    process.env.PYTHON ?? "python3",
    ["-c", pythonImports],
    {
      input: JSON.stringify(pyPaths),
      encoding: "utf8",
      maxBuffer: 16 * 1024 * 1024,
    },
  );
  if (python.status !== 0)
    throw new Error(`Python import parsing failed: ${python.stderr}`);
  for (const [path, specifier, level] of JSON.parse(python.stdout)) {
    if (specifier === null) {
      diagnostics.push(
        `${relative(root, path)}: computed imports cannot be checked against Plugin boundaries`,
      );
      continue;
    }
    if (level) {
      let base = dirname(path);
      for (let n = 1; n < level; n++) base = dirname(base);
      check(path, resolve(base, ...specifier.split(".")), specifier);
    } else {
      const parts = specifier.split(".");
      if (
        parts[0] === "plugins" ||
        parts[0] === "apps" ||
        parts[0] === "packages"
      )
        check(path, join(root, ...parts), specifier);
      if (pythonPackages.has(parts[0]))
        check(path, pythonPackages.get(parts[0]), specifier);
    }
  }
  return [...new Set(diagnostics)];
}
if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const diagnostics = await checkPluginBoundaries(
    fileURLToPath(new URL("../", import.meta.url)),
  );
  if (diagnostics.length) {
    console.error(diagnostics.join("\n"));
    process.exitCode = 1;
  } else
    console.log("Plugin frontend and backend import boundaries are valid.");
}
