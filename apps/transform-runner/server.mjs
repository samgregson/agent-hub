import { runTransform } from "./runner.mjs";

const decoder = new TextDecoder();
let active = false;

function json(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      "content-type": "application/json",
      "cache-control": "no-store",
    },
  });
}

async function boundedBody(request, limit) {
  if (!request.body) return null;
  const reader = request.body.getReader();
  const chunks = [];
  let total = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    total += value.length;
    if (total > limit) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.length;
  }
  return decoder.decode(body);
}

export async function handle(request) {
  const path = new URL(request.url).pathname;
  if (request.method === "GET" && path === "/health") {
    return json({ status: "ok" });
  }
  if (request.method === "GET" && path === "/runtime") {
    return json({ deno: Deno.version.deno, pyodide: "314.0.7" });
  }
  if (request.method !== "POST" || path !== "/execute") {
    return json({ code: "not_found" }, 404);
  }
  if (active) return json({ code: "busy" }, 429);
  active = true;
  try {
    const body = await boundedBody(request, 128_000);
    if (body === null) return json({ code: "input_limit" }, 413);
    let payload;
    try {
      payload = JSON.parse(body);
    } catch {
      return json({ code: "invalid_request" }, 422);
    }
    const result = await runTransform(payload);
    if (result.ok) return json(result);
    const status = {
      invalid_request: 422,
      input_limit: 413,
      output_limit: 413,
      execution_failed: 422,
      timeout: 504,
      runner_failed: 502,
    }[result.code] ?? 502;
    return json(result, status);
  } finally {
    active = false;
  }
}

if (import.meta.main) {
  Deno.serve({ hostname: "0.0.0.0", port: 8000 }, handle);
}
