---
status: accepted
---

# Use one Deno-hosted Pyodide runner for Transform execution

Transform previews and durable Transform Runs use the same host-side Pyodide runtime inside an isolated Deno runner. This avoids divergent browser and server Python behavior. The existing Python API authorizes Project access, captures inputs, and persists Definitions, Runs, and explicit saves; it sends only bounded inputs and source to the runner. Preview responses are transient, while durable Runs retain the output and provenance. The runner's exact Deno, Pyodide, Python, and package identities must be pinned and recorded before execution is enabled.

Deno permissions alone are insufficient for arbitrary user-authored code, so the runner also needs an operating-system isolation boundary and resource limits. Pyodide-in-Deno compatibility must be demonstrated in a small execution prototype before the runtime is shipped.
