# Citizen-developer data transforms

Research date: 2026-09-30

Decision update: [ADR 0007](../adr/0007-use-one-deno-hosted-pyodide-runner.md) selects one Deno-hosted Pyodide runner for both previews and durable Transform Runs. The staged browser-Pyodide recommendation below is retained as research context, not the current implementation direction.

## Conclusion

Agent Hub should eventually offer a **host-owned Transform Run**: a durable, approved execution that reads explicitly selected project values and produces a Dataset, Result Set, or Artifact through an explicit save action. It is a useful escape hatch between direct JSON bindings and asking every user to develop an MCP server.

Do not make a browser Python runtime the authoritative executor. Pyodide is a promising *local, interactive workbench* for a later trusted-user experience, but browser state disappears with the session, can be altered by the client, and cannot provide the durable server-side provenance, shared-project access control, or dependable batch lifecycle required by Agent Hub.

For the first delivery, keep direct bindings deliberately limited and ask the user to use a curated Plugin for non-trivial transformations. The next delivery should be a narrowly scoped, host-executed transform runner, with a reviewed Python subset/runtime and defence in depth. A client-side Pyodide editor may later use that same Transform definition as its source and submit an explicit, reproducible host execution.

## What the product needs

The feature is not a general notebook. A transform is a project-owned, inspectable operation:

```text
selected Dataset / Result Set / Artifact values
    -> Transform Definition (source, runtime version, declared inputs/outputs)
    -> approved Transform Run
    -> persisted output + provenance
```

It fills the gap where a user needs a small reshape, filter, join, derived field, or aggregation but no specialised MCP tool exists. It must not become an implicit execution engine for arbitrary output parsers or bindings.

## Findings from primary sources

### Pyodide in the browser

Pyodide is CPython compiled to WebAssembly for browser and Node.js use. It can call Web APIs and offers a JavaScript/Python FFI, so it is technically suitable for an interactive Python editor running in a Web Worker. It supports many scientific packages, including NumPy and pandas; packages not already built for Pyodide need either a pure-Python wheel or a WebAssembly/Emscripten build. [Pyodide overview](https://pyodide.org/en/stable/), [Pyodide packages](https://pyodide.org/en/stable/usage/packages-in-pyodide.html), [micropip package constraints](https://micropip.pyodide.org/en/latest/project/usage.html)

Pyodide's default Emscripten filesystem is in-memory and vanishes on reload. Its optional IndexedDB-backed filesystem requires explicit asynchronous `syncfs()` to persist data, and browser code cannot freely load a user's local files. That makes it unsuitable as the source of truth for a project-shared Dataset or run history. [Pyodide filesystems](https://pyodide.org/en/stable/usage/file-system.html), [Pyodide FAQ: local files](https://pyodide.org/en/stable/usage/faq.html#why-cant-i-load-files-from-the-local-file-system)

Most importantly, a Pyodide program runs with the browser's authority. Pyodide's JavaScript module defaults to `globalThis`; a program can reach embedding JavaScript/browser APIs unless supplied a restricted `jsglobals` object. A Web Worker keeps work off the UI and has no DOM, but is not by itself a product authorization boundary: it still communicates with the browser APIs available to it. WebAssembly is not, by itself, a product authorization boundary. It is reasonable for private previews, but the server must re-execute or validate anything that becomes durable project state. [Pyodide JavaScript API](https://pyodide.org/en/stable/usage/api/js-api.html), [Pyodide Web Workers](https://pyodide.org/en/stable/usage/webworker.html)

Excel support should not drive the first runtime decision. Pyodide's current package inventory includes pandas, polars, pyarrow, and python-calamine, making useful table and spreadsheet import flows feasible; not every Python package is available. Third-party packages remain subject to WebAssembly wheel availability and browser memory/download constraints. A later server runner is a much more dependable place to support vetted Excel libraries and large files. [Pyodide package support](https://pyodide.org/en/stable/usage/packages-in-pyodide.html), [micropip constraints](https://micropip.pyodide.org/en/latest/project/usage.html)

### Deno on the server

Deno is secure by default: filesystem, network, environment, subprocess, and FFI access are denied unless explicitly granted and can be scoped to resources. That makes it a credible JavaScript/TypeScript execution adapter, not a reason to grant broad access. [Deno permissions](https://docs.deno.com/runtime/reference/permissions/), [Deno security model](https://docs.deno.com/runtime/fundamentals/security/)

Deno's own security guidance says permission limits alone are insufficient for completely untrusted code: use limited permissions, a frozen/cached dependency graph, reduced-worker permissions, and OS or VM isolation. `--allow-run` and FFI effectively invalidate the sandbox because a subprocess/native library can escape Deno's permission model. [Deno: executing untrusted code](https://docs.deno.com/runtime/fundamentals/security/#executing-untrusted-code), [Deno permissions](https://docs.deno.com/runtime/reference/permissions/)

Therefore a Deno runner is a viable later *implementation* for JavaScript/TypeScript transforms only if it receives data over a narrow request/response channel, runs with no network, no environment, no subprocess, no FFI, and no host filesystem permissions beyond a job-specific temporary directory, and has CPU, memory, output-size, timeout, and concurrency limits. It cannot safely receive database credentials or a mounted project directory. For arbitrary server-side user code, a disposable OS/container/VM boundary is also required; Deno itself recommends OS-level sandboxing or a VM/microVM for untrusted code. [Deno: executing untrusted code](https://docs.deno.com/runtime/fundamentals/security/#executing-untrusted-code)

## Recommended staged architecture

### Stage 0 — Keep bindings direct

- Bindings remain declarative JSON path assignment, including explicit scalar-to-record broadcast and collection-to-one-argument injection.
- Non-standard transformation uses a curated MCP tool. This keeps the first dataflow graph readable and avoids an unbounded code-execution surface.

### Stage 1 — Host-owned Python Transform Run

- Add a first-class Transform Definition and Transform Run, beside—not inside—Bindings.
- Inputs are immutable snapshots selected by IDs and JSON paths. The runner sees a read-only `/input`, a private `/work`, and explicit JSON parameters; the host passes those through a short-lived isolated process or VM.
- The runner returns one declared output manifest (logical result name, schema/format, hash) and bounded JSON/file payloads. It cannot read the project VFS directly, access PostgreSQL, receive service credentials, make network calls, launch processes, or import arbitrary packages.
- Pin the Python runtime and allow-listed package set. Record the transform source hash, runtime/package manifest, input snapshot hashes, initiator, approval, limits, logs (redacted), and output hash.
- An agent may propose a transform or save/update a Transform Definition, subject to the same durable-change approval policy as a user-visible Dataset. Direct user execution is authorized but still policy-limited.
- A single-run output is transient until the user or approved agent explicitly saves it as a Dataset or Artifact. A per-record transform executed through the Batch Execution Module produces a Result Set. This preserves the existing distinction between computation and curated project output.

Start with a small supported data model—JSON objects/lists and a documented dataframe-like convenience API—rather than allowing imports, user dependencies, files, or Excel. Host execution makes the run reproducible and usable in agent-initiated batch flows.

### Stage 2 — Local Pyodide workbench

- Offer a browser Web Worker for instant experimentation against a downloaded, read-only input snapshot.
- Treat it as a preview only. Display that it is local and non-authoritative; the user explicitly submits the Transform Definition to the host to produce a durable run.
- Host and client use the same declared input/output contract, but do not promise bit-for-bit equality across browser and server runtimes. The durable result is always the host execution.

This delivers the approachable “try a little Python” experience without asserting that client code is trustworthy or persistent.

### Stage 3 — Vetted file/data integrations

- Add explicit Source import/export operations and host-mediated temporary file handles for `.csv`, then `.xlsx` through an approved package/runtime.
- A Transform Run gets only explicit read handles and an explicit output channel, never a broad VFS mount. Record each source's immutable version/hash in provenance.
- Consider Deno for JavaScript transforms as a second adapter only when there is a real demand. The domain contract remains runtime-neutral.

## Boundaries and relationship to batches

- A Transform Run may be invoked singly or by the same durable batch executor, but is not itself a Binding.
- For one-to-many use, the Batch Definition maps Dataset records to Transform inputs and creates a Result Set exactly as for an MCP tool. First-item validation and approved concurrency policy apply.
- A transform producing a collection is a single-result operation. Turning that collection into thousands of further executions remains a later explicit bulk-to-bulk design, never an inferred broadcast.
- The read-only dataflow graph shows Transform Definitions/Runs as nodes and their input/output provenance edges. It should show cardinality (`one`, `per-record`, `collection`) rather than inspecting arbitrary Python source to infer behaviour.

## Decisions supported

1. Keep the initial direct Binding primitive small and portable MCP-focused.
2. Plan a separate host-owned Transform Run for citizen-developer manipulation.
3. Use Pyodide later for local iteration, not durable authority.
4. Do not grant arbitrary transform code network, filesystem, process, FFI, database, secret, or package-install authority.
5. Do not make Excel support, browser execution, or JavaScript-vs-Python selection a prerequisite for the current MCP batch/dataflow issues.
