import { loadPyodide } from "npm:pyodide@314.0.7";

function respond(value) {
  Deno.stdout.writeSync(new TextEncoder().encode(JSON.stringify(value)));
}

try {
  const request = JSON.parse(await new Response(Deno.stdin.readable).text());
  const pyodide = await loadPyodide({
    jsglobals: Object.freeze({}),
    stdout: () => {},
    stderr: () => {},
  });
  pyodide.globals.set("source", request.source);
  pyodide.globals.set("input_json", JSON.stringify(request.inputs));
  pyodide.globals.set("parameters_json", JSON.stringify(request.parameters));
  const outputJson = pyodide.runPython(`
import json
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
      pyodide: pyodide.version,
    });
  }
} catch {
  respond({ ok: false, code: "execution_failed" });
}
