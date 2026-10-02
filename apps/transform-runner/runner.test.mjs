import { runTransform } from "./runner.mjs";
import { handle } from "./server.mjs";

Deno.test("runtime endpoint reports the pinned package lock", async () => {
  const response = await handle(new Request("http://runner/runtime"));
  const runtime = await response.json();
  if (
    response.status !== 200 || runtime.deno !== Deno.version.deno ||
    runtime.pyodide !== "314.0.7" || runtime.packageHash.length !== 64 ||
    runtime.limits.timeoutMs !== 10_000 ||
    runtime.limits.maxOutputBytes !== 128_000 ||
    runtime.limits.maxConcurrent !== 1
  ) {
    throw new Error(`Unexpected runtime identity: ${JSON.stringify(runtime)}`);
  }
});

Deno.test("fresh restricted Pyodide executions share the preview and run contract", async () => {
  const request = {
    source: `
counter = globals().get("counter", 0) + 1
def transform(inputs, parameters):
    import js
    try:
        open("/app/worker.mjs").read()
        host_file_visible = True
    except Exception:
        host_file_visible = False
    return {
        "value": inputs["load"] * parameters["factor"],
        "counter": counter,
        "denoVisible": hasattr(js, "Deno"),
        "fetchVisible": hasattr(js, "fetch"),
        "globalThisVisible": hasattr(js, "globalThis"),
        "functionVisible": hasattr(js, "Function"),
        "hostFileVisible": host_file_visible,
    }
`,
    inputs: { load: 3 },
    parameters: { factor: 2 },
  };

  const preview = await runTransform(request);
  const durable = await runTransform(request);

  for (const result of [preview, durable]) {
    if (!result.ok) throw new Error(`Transform failed: ${result.code}`);
    if (
      JSON.stringify(result.output) !== JSON.stringify({
        value: 6,
        counter: 1,
        denoVisible: false,
        fetchVisible: false,
        globalThisVisible: false,
        functionVisible: false,
        hostFileVisible: false,
      })
    ) throw new Error(`Unexpected output: ${JSON.stringify(result.output)}`);
  }
});

Deno.test("time and output limits terminate a transform", async () => {
  const loop = await runTransform({
    source: "def transform(inputs, parameters):\n    while True: pass\n",
    inputs: {},
    parameters: {},
  }, { timeoutMs: 100 });
  if (loop.ok || loop.code !== "timeout") {
    throw new Error(`Unexpected timeout result: ${JSON.stringify(loop)}`);
  }

  const oversized = await runTransform({
    source:
      "def transform(inputs, parameters):\n    return {'data': 'x' * 5000}\n",
    inputs: {},
    parameters: {},
  }, { maxOutputBytes: 1000 });
  if (oversized.ok || oversized.code !== "output_limit") {
    throw new Error(
      `Unexpected output limit result: ${JSON.stringify(oversized)}`,
    );
  }
});
