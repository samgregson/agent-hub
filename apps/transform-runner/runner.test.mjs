import { runTransform } from "./runner.mjs";

Deno.test("fresh restricted Pyodide executions share the preview and run contract", async () => {
  const request = {
    source: `
counter = globals().get("counter", 0) + 1
def transform(inputs, parameters):
    import js
    return {
        "value": inputs["load"] * parameters["factor"],
        "counter": counter,
        "denoVisible": hasattr(js, "Deno"),
        "fetchVisible": hasattr(js, "fetch"),
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
