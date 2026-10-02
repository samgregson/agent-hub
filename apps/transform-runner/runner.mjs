const encoder = new TextEncoder();
const decoder = new TextDecoder();

export const RUNNER_LIMITS = Object.freeze({
  timeoutMs: 10_000,
  maxInputBytes: 128_000,
  maxOutputBytes: 128_000,
  maxSourceBytes: 64_000,
  maxConcurrent: 1,
});

export async function runTransform(request, limits = {}) {
  const timeoutMs = limits.timeoutMs ?? RUNNER_LIMITS.timeoutMs;
  const maxInputBytes = limits.maxInputBytes ?? RUNNER_LIMITS.maxInputBytes;
  const maxOutputBytes = limits.maxOutputBytes ?? RUNNER_LIMITS.maxOutputBytes;
  if (
    !request || typeof request.source !== "string" ||
    request.source.length === 0 ||
    encoder.encode(request.source).length > RUNNER_LIMITS.maxSourceBytes ||
    !request.inputs || typeof request.inputs !== "object" ||
    Array.isArray(request.inputs) ||
    !request.parameters || typeof request.parameters !== "object" ||
    Array.isArray(request.parameters)
  ) return { ok: false, code: "invalid_request" };

  const payload = encoder.encode(
    JSON.stringify({ ...request, maxOutputBytes }),
  );
  if (payload.length > maxInputBytes) return { ok: false, code: "input_limit" };

  const child = new Deno.Command(Deno.execPath(), {
    args: [
      "run",
      "--cached-only",
      "--no-prompt",
      "--allow-read=/app,/deno-dir",
      "--deny-net",
      "--deny-env",
      "--deny-run",
      "--deny-ffi",
      "/app/worker.mjs",
    ],
    clearEnv: true,
    env: { DENO_DIR: "/deno-dir", DENO_NO_PROMPT: "1" },
    stdin: "piped",
    stdout: "piped",
    stderr: "null",
  }).spawn();

  let expired = false;
  const timer = setTimeout(() => {
    expired = true;
    try {
      child.kill("SIGKILL");
    } catch { /* already finished */ }
  }, timeoutMs);
  try {
    const writer = child.stdin.getWriter();
    await writer.write(payload);
    await writer.close();
    const result = await child.output();
    if (expired) return { ok: false, code: "timeout" };
    if (!result.success || result.stdout.length > maxOutputBytes + 2048) {
      return { ok: false, code: "runner_failed" };
    }
    const response = JSON.parse(decoder.decode(result.stdout));
    if (!response || typeof response.ok !== "boolean") {
      return { ok: false, code: "runner_failed" };
    }
    return response;
  } catch {
    return { ok: false, code: expired ? "timeout" : "runner_failed" };
  } finally {
    clearTimeout(timer);
  }
}
