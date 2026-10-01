---
status: accepted
---

# Use one Deno-hosted Pyodide runner for Transform execution

Transform previews and durable Transform Runs use the same host-side Pyodide runtime inside an isolated Deno runner. This avoids divergent browser and server Python behavior. The existing Python API authorizes Project access, captures inputs, and persists Definitions, Runs, and explicit saves; it sends only bounded inputs and source to the runner. Preview responses are transient, while durable Runs retain the output and provenance. The runner's exact Deno, Pyodide, Python, and package identities must be pinned and recorded before execution is enabled.

Deno permissions alone are insufficient for arbitrary user-authored code, so the runner also needs an operating-system isolation boundary and resource limits. Local prototype branch `prototype/deno-pyodide` at `bdab9fc` demonstrated Pyodide 314.0.7 running under Deno 2.9.7 with the container offline and read-only; preview and durable modes called the same Transform function. That establishes runtime compatibility, not a production security boundary. Per-invocation isolation, timeouts, limits, and package controls remain execution requirements.
