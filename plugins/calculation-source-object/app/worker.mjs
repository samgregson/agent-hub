import { loadPyodide } from "npm:pyodide@314.0.7";

const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });

function respond(value) {
  Deno.stdout.writeSync(encoder.encode(JSON.stringify(value)));
}

try {
  const reader = Deno.stdin.readable.getReader();
  const chunks = [];
  let inputBytes = 0;
  let tooLarge = false;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    inputBytes += value.byteLength;
    if (inputBytes > 96_256) {
      tooLarge = true;
      await reader.cancel();
      break;
    }
    chunks.push(value);
  }
  if (tooLarge) {
    respond({ ok: false, code: "input_limit" });
  } else {
    const input = new Uint8Array(inputBytes);
    let offset = 0;
    for (const chunk of chunks) {
      input.set(chunk, offset);
      offset += chunk.byteLength;
    }
    const rawRequest = decoder.decode(input);
    const pyodide = await loadPyodide({
      jsglobals: Object.freeze({}),
      stdout: () => {},
      stderr: () => {},
    });
    pyodide.FS.writeFile("/tmp/cs_object.whl", await Deno.readFile("/app/cs_object.whl"));
    pyodide.globals.set("request_json", rawRequest);
    const response = pyodide.runPython(`
import json
import pathlib
import sys
import zipfile

request = json.loads(request_json)
site = pathlib.Path("/tmp/cso-site")
site.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile("/tmp/cs_object.whl") as wheel:
    wheel.extractall(site)
sys.path.insert(0, str(site))

source_path = pathlib.Path("/tmp/calculation.cso.py")
source_path.write_text(request["source"], encoding="utf-8")
from cso_python.execution import execute
result = execute(source_path, function=request["function"], inputs=request["inputs"])
json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
`);
    if (encoder.encode(response).length > 768_000) {
      respond({ ok: false, code: "output_limit" });
    } else {
      const execution = JSON.parse(response);
      if (execution.ok !== true || typeof execution.execution !== "object") {
        respond({ ok: false, code: "execution_failed", response: execution });
      } else {
        respond({ ok: true, execution: execution.execution, pyodide: pyodide.version });
      }
    }
  }
} catch {
  respond({ ok: false, code: "execution_failed" });
}
