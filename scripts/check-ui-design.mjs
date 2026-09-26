import { readdir, readFile } from "node:fs/promises";
import { extname, join, relative } from "node:path";

const root = new URL("../", import.meta.url).pathname;
const uiRoots = [
  "apps/web/src/shared/ui",
  "apps/web/src/modules/datasets",
  "apps/web/src/modules/plugin-gateway",
];
const violations = [];

async function files(directory) {
  const entries = await readdir(join(root, directory), { withFileTypes: true });
  const nested = await Promise.all(
    entries.map(async (entry) => {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) return files(path);
      return extname(entry.name) === ".css" ? [path] : [];
    }),
  );
  return nested.flat();
}

for (const directory of uiRoots) {
  for (const path of await files(directory)) {
    const source = await readFile(join(root, path), "utf8");
    if (/#[0-9a-f]{3,8}\b/i.test(source)) {
      violations.push(
        `${relative(root, join(root, path))}: use a named design token instead of a literal colour`,
      );
    }
    if (
      source
        .split("\n")
        .some(
          (line) =>
            /font-size:/i.test(line) && !/font-size:\s*var\(/i.test(line),
        )
    ) {
      violations.push(
        `${relative(root, join(root, path))}: use a named typography token instead of a literal font size`,
      );
    }
  }
}

if (violations.length) {
  console.error(`UI design violations:\n${violations.join("\n")}`);
  process.exitCode = 1;
} else {
  console.log("Shared and navigator UI uses design tokens.");
}
