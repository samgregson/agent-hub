import { build } from "esbuild";
import { readFile, mkdir, writeFile } from "node:fs/promises";

// web-ifc has no public wasmBinary option. Inject the pinned binary at build
// time so the sandbox needs neither network, blob URLs nor a WASM worker.
const result = await build({
  entryPoints: ["src/main.tsx"],
  bundle: true,
  minify: true,
  format: "iife",
  platform: "browser",
  target: "es2022",
  write: false,
  define: { "process.env.NODE_ENV": '"production"' },
  plugins: [
    {
      name: "embedded-ifc-wasm",
      setup(builder) {
        builder.onLoad({ filter: /web-ifc-api\.js$/ }, async ({ path }) => {
          const source = await readFile(path, "utf8");
          if (source.split("noInitialRun: true,").length !== 3)
            throw new Error(
              "web-ifc initialization changed; review the WASM embedding adapter.",
            );
          const wasm = await readFile(
            new URL("./node_modules/web-ifc/web-ifc.wasm", import.meta.url),
          );
          return {
            contents:
              `const embeddedIfcWasm=Uint8Array.from(atob(${JSON.stringify(wasm.toString("base64"))}),c=>c.charCodeAt(0));\n` +
              source.replaceAll(
                "noInitialRun: true,",
                "noInitialRun: true, wasmBinary: embeddedIfcWasm,",
              ),
            loader: "js",
          };
        });
      },
    },
  ],
});
const css = await readFile("src/style.css", "utf8");
const script = result.outputFiles[0].text.replaceAll("</script", "<\\/script");
const html = `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>IFC viewer</title><style>${css}</style><div id="root"></div><script>${script}</script></html>`;
if (Buffer.byteLength(html) > 12_000_000)
  throw new Error("IFC UI resource exceeds its 12 MB budget");
await mkdir("dist", { recursive: true });
await writeFile("dist/index.html", html);
console.log(`Built standalone IFC App (${Buffer.byteLength(html)} bytes).`);
