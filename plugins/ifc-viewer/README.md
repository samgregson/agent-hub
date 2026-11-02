# IFC viewer MCP Plugin

An independently deployable FastMCP server and bundled React MCP App. The
frontend uses Three.js, React Three Fiber, Drei and That Open's open-source
`web-ifc` WASM parser. The backend uses IfcOpenShell to extract structured
properties for calculations. Neither side imports Agent Hub or another Plugin.

## Run

```sh
cd plugins/ifc-viewer/app
npm ci
npm run typecheck
npm test
npm run build
cd ..
uv sync --frozen
uv run python -m agent_hub_ifc_viewer._server
```

The Streamable HTTP endpoint is `/mcp` on port 8000. From the repository root,
`docker compose up --build ifc-viewer` exposes it on localhost:8004. Enable
**IFC viewer** in the Project's Plugins view. No host frontend changes are
needed: both captured MCP results and Artifact snapshots use the standard App
resource `ui://agent-hub-ifc-viewer/view.html`.

## Calculation composition

1. Bind IFC STEP text to `inspect_ifc_objects(ifc_text)`. Its `objects` array
   contains `globalId`, `expressId`, `ifcType`, `name` and IFC property sets.
2. Use those records as Dataset or Workflow Map inputs. Preserve `globalId`
   alongside calculated outputs. Express IDs only identify entities within the
   exact file; GlobalIds are the cross-tool join key.
3. Transform calculation outputs into metadata rows and call
   `prepare_ifc_view(ifc_text, metadata, colour_by)`:

```json
{
  "metadata": [
    {
      "globalId": "<the IFC object's GlobalId>",
      "values": { "status": "pass", "utilisation": 0.75, "reviewed": false }
    }
  ],
  "colour_by": "status"
}
```

The result retains the original IFC text, SHA-256, typed metadata overlay and
colour selection. It can be inspected without recalculation. Unknown or duplicate
GlobalIds fail explicitly. Metadata values are JSON scalars; include units and
calculation provenance as explicit keys when needed. Assigning metadata does not
change IFC attributes, property sets or geometry.

Click an object or use the accessible object selector to inspect IFC attributes,
property sets and assigned metadata. Assign a text, number, boolean or null value
in the inspector. Colours are categorical, including for numeric values, with a
legend and grey for unassigned objects. Orbit, zoom and fit use Drei controls.

Preview edits are transient because the host's preview bridge prohibits tool
calls. **Export view inputs** exposes selectable JSON; pass those inputs to
`prepare_ifc_view` to persist a new host-managed Tool Result Snapshot. Reopening
an older snapshot always shows its captured values.

## Bounds and sandbox

- Portable MCP tools accept up to 400,000 UTF-8 bytes of IFC STEP text. Complete
  structured output is limited to 768,000 bytes. This is an initial inline-file
  implementation; large durable models need a host file/resource transport.
- A local file chooser supports previews up to 25 MB without uploading the file.
  Large local previews cannot be saved through the bounded inline tool contract.
- Rendering is capped at 20,000 geometry parts and a 512 MiB parser memory budget.
  Parsing currently runs on the browser's main thread. Very complex models may
  pause the UI; worker-based parsing and geometry instancing are future work.
- The single-threaded WASM binary is embedded at build time. The adapter checks
  the pinned web-ifc initialization shape and fails a build if it changes.
- The reviewed IFC catalog entry permits WebAssembly compilation and a 12 MB UI
  resource. Other Plugins retain their original CSP and resource limits.
  Network, workers, frames, form submission and JavaScript eval remain blocked.
- Only IFC STEP files are supported, not IFCZIP or IFCXML. Invalid/no-geometry
  models and unavailable WebGL produce visible errors.
- The viewer displays results; it does not establish engineering suitability.

## Validation

```sh
npm --prefix app run typecheck
npm --prefix app test
npm --prefix app run build
uv run pytest -q src/agent_hub_ifc_viewer/_server_test.py
CHROMIUM_PATH=/usr/bin/chromium npm --prefix app run test:browser
```

The browser smoke uses the same opaque-origin iframe sandbox and CSP as the
host. It exercises WASM/geometry, properties, metadata edits, colour selection,
portable export, phone width and saved Artifact replay with a generated IFC4 beam.

## Main agent usage

The enabled Plugin exposes `get_ifc_guide`, backed by this Plugin's
[AGENT_GUIDE.md](AGENT_GUIDE.md) and an ordinary Markdown MCP resource. The main
agent can discover and read that guide without importing Plugin code. It explains
how to read a Project IFC, inspect objects, recover the saved structured result,
assign metadata by GlobalId and prepare a coloured view. Instructions cannot
override the host's permissions or approval controls.

Try in a Project with **IFC viewer** enabled and `model.ifc` in its Library:

> Read /project/model.ifc. Assign reviewStatus "needs-review" to every IfcBeam
> and colour the model by reviewStatus. Preserve the IFC and save the view.

The file must exist as a Project File; choosing a browser-local file does not
make it accessible to the main agent. The main agent can use native read-only
PTC to read exact Project text, inspect/filter objects and prepare a transient
view without copying source into model messages. Ordinary MCP arguments remain
unchanged. PTC cannot save snapshots or create/edit files or Workflows. Saving
uses the normal approval-gated tools outside eval; reusable Workflow file
bindings avoid copying the IFC into model-generated save arguments.

A repeatable integration test exercises the actual main-agent graph against this
service with a deterministic tool-calling model:

```sh
AGENT_HUB_IFC_PYTHON=plugins/ifc-viewer/.venv/bin/python \
  uv run --package agent-hub-api pytest -q tests/integration/ifc_main_agent_test.py
```

Run that command from the repository root after installing both locked Python
environments. It starts and stops the independent MCP service automatically.
This verifies native PTC, nullable array inputs, metadata assignment, no PTC
persistence, and approval-gated Workflow creation. It then exercises the normal
host Workflow execution path. The browser fixture wraps that captured Workflow
output for App-host testing. It does not measure live-model task quality.
