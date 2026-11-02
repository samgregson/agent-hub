---
status: accepted
---

# Isolate MCP App implementations and join IFC results by GlobalId

Each `plugins/<plugin>/` directory is a separate deployable application boundary,
including its backend and optional frontend. Host application code and other
Plugins must not import it, and a Plugin must not import host or sibling Plugin
code. External library dependencies and imports inside the same Plugin remain
allowed. Composition uses MCP tools/resources and portable JSON contracts.

The architecture gate parses JavaScript/TypeScript import, export, require and
literal dynamic-import syntax, resolves local aliases and workspace package
names, checks package dependencies, and parses Python imports using its AST.
It rejects imports crossing any Plugin directory boundary in either direction.
Computed runtime imports are rejected because their targets cannot be checked.
Deployment metadata such as endpoint URLs and tool names remain ordinary host
catalog configuration; they are not implementation imports.

The IFC Plugin uses web-ifc, Three.js, React Three Fiber and Drei in its own
bundled UI. IfcOpenShell extracts object records on its backend. IFC `GlobalId`
is the join key for scalar metadata overlays, including calculated Workflow Map
outputs. Express IDs are file-local display/lookup identifiers. Source IFC stays
unchanged; an overlay is captured in a portable MCP result rather than written
into the IFC or stored in Plugin memory.

The initial transport embeds bounded IFC STEP text in the result so saved
previews need no model fetch or rerun. Large durable IFC resources are deferred
until a generic host file transport exists. Browser previews may load larger
local files, but remain transient. Host previews prohibit tool calls, so UI edits
are exported and submitted through the ordinary tool path for persistence.

WebAssembly is denied by default. A deployment-reviewed catalog flag grants
`wasm-unsafe-eval` only to the IFC UI resource; neither MCP resource metadata nor
the Plugin client can self-authorize it. The sandbox still denies network,
workers and JavaScript eval. The IFC client's UI resource budget is independently
bounded at 12 MB; ordinary tool-output limits remain unchanged.
