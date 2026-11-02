# MCP Apps that fit Agent Hub

This is the preferred development pattern for independently deployed MCP Apps.
Use the IFC Plugin as the reference for structured object data and interactive 3D
views. The host remains general purpose: do not add App-specific imports, routes,
renderers or tool dispatch to the frontend or API.

## Own one complete Plugin

Keep the MCP server, UI source, dependency locks, build, container, tests and agent
usage guide together under `plugins/<plugin>/`. Import libraries and your own
implementation; never import the host or a sibling Plugin. Agent Hub's architecture
gate enforces both frontend and backend boundaries.

Expose ordinary MCP tools with useful descriptions and exact JSON Schemas. An
interactive tool links to a versioned `ui://` resource containing
`text/html;profile=mcp-app`. Package a self-contained production HTML resource.
Avoid CDN scripts, remote fonts, runtime package imports and hidden model fetches.
A reviewed catalog entry enables the endpoint, tools and UI resource.

## Make the main agent capable

Keep domain recipes in a Plugin-owned `AGENT_GUIDE.md`. Serve the same guide as a
Markdown MCP resource and through a clearly described read-only guide tool. Keep
the tool description short; load the full recipe only when needed. Guides must
explain source selection, input shapes, stable identifiers, output locations,
follow-up edits, Workflow composition, size bounds and failure recovery.

Examples must use real tool names and distinguish a browser-local file from an
authorized Project File. The guide cannot enable Plugins, change Project scope,
change approvals, or grant itself capabilities. Do not duplicate a Plugin's full
recipe in Agent Hub's system prompt.

Use structured results with stable domain IDs, schema version and provenance.
Keep model-visible text concise. The host returns the ID of a saved result; the
agent can load its exact structured output for a follow-up call. For reusable
calculations, bind Project Files and results through Workflow instead of asking
the model to repeat large source files as tool arguments.

For read-only exploration, the main agent can use native programmatic tool
calling (PTC) inside `eval`. Exact Project File contents and intermediate MCP
results stay in interpreter variables. The Plugin receives its ordinary MCP
arguments; there is no host file-reference schema extension. PTC tools return
`{content, structuredContent}` and do not automatically save snapshots.

Only reviewed, server-declared read-only MCP tools and explicitly named read
operations are available. PTC has no file writes, Artifact/Dataset/Function
mutations, Workflow creation/preparation/execution, shell or subagent delegation.
Each eval starts fresh and should return only a compact summary. Save or mutate
through the normal tools outside eval, where approval applies. Use approved
Workflow file bindings for large durable compositions. Do not return an entire
IFC to the model just to submit it again for saving.

## Give the App the available space

Treat the iframe as the application viewport. It may be a narrow workspace panel,
a full-width Library preview, a phone screen, or an expanded host dialog.

- Put the work product first: model, drawing, table or report. Keep the header
  compact and avoid repeating the host's title, Artifact ID, version or provenance.
- Use one compact toolbar for view controls. Put secondary options, raw JSON and
  diagnostics behind disclosures. Do not show a file chooser above every saved
  result unless opening another local file is the primary task.
- Use viewport-relative or flexible stage sizing, with a useful minimum. Do not
  hard-code desktop canvas widths or assume the outer browser viewport width.
- Let controls wrap. Stack or collapse inspectors when the iframe is narrow.
  Long IDs and values must wrap or scroll locally, never widen the whole page.
- Give a 3D canvas a real height. Resize with its container. Provide fit/reset,
  readable legends, selection feedback and an accessible object selector.
- Keep meaningful local state when the host expands or restores the view. The
  host preserves the iframe; do not reload just because its viewport changes.
- Honour the standard MCP host theme context. Use App-local CSS variables and
  system fonts; do not import host CSS or attempt to read its DOM. Context-change
  notifications are partial: use the SDK's merged `getHostContext()` state rather
  than resetting missing fields such as theme.

Agent Hub owns the trusted App title and expand/restore controls. Expanded mode
is a host-owned dialog with a keyboard exit; the same sandbox and iframe remain
in use. Apps may use standard display-mode context when provided. They must
remain usable inline and must not require unrestricted browser fullscreen.
Keyboard events inside an iframe do not reach the host. When expanded, handle
Escape inside the App by calling the SDK's `requestDisplayMode({mode: "inline"})`.
The trusted host toolbar remains the exit path for Apps without that handler.

## Make loading and edits honest

Register tool-result handlers before connecting with the MCP Apps SDK. Support
direct structured results, saved Workflow outputs and captured Artifact envelopes, without rerunning
the original tool. Treat input/result data as untrusted; validate the shape and
render strings as text. Show useful loading, unsupported-result, parse and WebGL
errors rather than a blank frame.

A saved preview is read-only at the host bridge. Local interaction is allowed,
but local changes are not automatically saved. Mark them as unsaved and provide
an explicit export/apply path. Never imply that choosing a local file uploads it,
that an export saves an Artifact, or that rendering a calculation verifies it.

## Keep capabilities bounded

Default sandbox: scripts only, opaque origin, no network, workers, form submission,
child frames or JavaScript eval. Request extra capabilities only when required;
the deployment catalog must review them. IFC needs WASM compilation and a larger
bounded UI resource; that grant applies only to its reviewed catalog entry.
Keep structured-result and UI-resource budgets separate. Document model/file limits
and fail clearly rather than truncating or silently dropping unmatched records.

## Test three different boundaries

1. **MCP conformance:** an ordinary client discovers the tools, guide and resource;
   contracts validate; errors and unknown identifiers are explicit.
2. **Main-agent integration:** the real agent graph reads Project inputs, invokes
   MCP inside native PTC, then leaves the interpreter before approval-gated saves. Deterministic
   models verify wiring; live-model evaluations separately test task quality.
3. **Embedded browser:** open the actual production UI through Agent Hub's App
   bridge and sandbox. Check content, object selection, expansion/restoration,
   state preservation, keyboard exit, narrow layout and unavailable resources.

A standalone App screenshot is useful but does not substitute for the embedded
test. State which services and model calls are real and which API records are
fixtures when reporting a smoke test.

Saved single MCP Workflow outputs open from **Final outputs → Open App**. The
Workflow Module resolves the producer from the immutable Run snapshot, then asks
Plugin Gateway for the currently enabled, reviewed UI at that captured version.
The host replays the saved step inputs and structured output in `McpAppFrame`;
opening a view never executes tools or creates an Artifact. Full output data is
retained alongside the view. This path stays generic and imports no Plugin code.
