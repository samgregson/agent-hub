import { loadPyodide } from "npm:pyodide@314.0.7";

function respond(value) {
  Deno.stdout.writeSync(new TextEncoder().encode(JSON.stringify(value)));
}

function boundedText(value, limit) {
  const text = typeof value === "string" ? value : String(value ?? "");
  return text.length <= limit ? text : `${text.slice(0, limit)}… [truncated]`;
}

function diagnosticFor(error, stderrLines) {
  return {
    type: boundedText(error?.type ?? error?.name ?? "Error", 160),
    message: boundedText(error?.message ?? error, 2_000),
    traceback: boundedText(error?.stack ?? "", 6_000),
    stderr: boundedText(stderrLines.join("\n"), 2_000),
  };
}

const stderrLines = [];
try {
  const request = JSON.parse(await new Response(Deno.stdin.readable).text());
  const pyodide = await loadPyodide({
    // Deno's npm cache is read-only in the runner container. Keep Pyodide's
    // lockfile from the pinned npm package, but load package wheels directly
    // from the matching release and cache them in the runner's temporary disk.
    packageBaseUrl: "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/",
    packageCacheDir: "/tmp/pyodide-package-cache/",
    jsglobals: Object.freeze({}),
    stdout: () => {},
    stderr: (line) => {
      stderrLines.push(boundedText(line, 1_000));
      if (stderrLines.join("\n").length > 2_000) stderrLines.shift();
    },
  });
  if (/^\s*(?:import\s+matplotlib|from\s+matplotlib)/m.test(request.source)) {
    pyodide.runPython("import os; os.environ['MPLBACKEND'] = 'Agg'");
    await pyodide.loadPackage("matplotlib");
  }
  pyodide.globals.set("source", request.source);
  pyodide.globals.set("input_json", JSON.stringify(request.inputs));
  pyodide.globals.set("parameters_json", JSON.stringify(request.parameters));
  const outputJson = pyodide.runPython(`
import json
import os
os.environ["MPLBACKEND"] = "Agg"
_scope = {}
exec(source, _scope)
_result = _scope["transform"](json.loads(input_json), json.loads(parameters_json))
json.dumps(_result, allow_nan=False)
`);
  if (new TextEncoder().encode(outputJson).length > request.maxOutputBytes) {
    respond({ ok: false, code: "output_limit" });
  } else {
    respond({
      ok: true,
      output: JSON.parse(outputJson),
      deno: Deno.version.deno,
      pyodide: pyodide.version,
    });
  }
} catch (error) {
  respond({
    ok: false,
    code: "execution_failed",
    diagnostic: diagnosticFor(error, stderrLines),
  });
}
