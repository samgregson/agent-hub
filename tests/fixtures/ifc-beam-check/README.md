# IFC engineering Workflow smoke

`transform.py` is example project-owned Function source, exercised by
`tests/integration/ifc_main_agent_test.py`. It uses the existing IFC App and host
Function runner; no new engineering App or cross-Plugin imports are needed.

The test authors a Function and Workflow through the main agent's actual tools,
previews missing inputs, then prepares and executes Runs through those tools.
The IFC MCP server and Deno/Pyodide calculations are real. Stores are in memory;
the initial agent sequence is scripted, not a live language-model evaluation.
The initial graph test verifies HITL interruption; the engineering extension
invokes the reviewed tool actions directly, without simulating extra approvals.

Graph:

```text
Project IFC ──► inspect_ifc_objects ──► Python Function ──► prepare_ifc_view
     └─────────────────────────────────────────────────► ifc_text
Workflow Input (beam_inputs by GlobalId) ──► Function
```

The Function covers simply supported beams with uniform imposed load only:
`5wL^4/(384EI)`, compared with an explicit span/limit ratio. It is not a complete
beam design or code check. Span and section properties are explicit test inputs,
not values inferred from the fixture geometry. For the 4 m example, 3 kN/m² load,
3 m tributary width, E=210 GPa, I=16,000,000 mm⁴ and L/360:

- Deflection: 8.928571 mm; limit: 11.111111 mm; status: `passes`.
- With I=800,000 mm⁴: 178.571429 mm; status: `fails`.
- No supplied inputs: `missing_inputs`, with the missing fields named.
- Duplicate/unknown GlobalIds, unsupported supports and zero inertia are rejected.

To repeat with the locked environments installed, start the existing runner:

```sh
docker build -f apps/python-runner/Dockerfile --target production -t agent-hub-ifc-runner .
docker run --rm -d --name ifc-engineering-runner -p 127.0.0.1:18009:8000 agent-hub-ifc-runner
AGENT_HUB_IFC_PYTHON=plugins/ifc-viewer/.venv/bin/python \
AGENT_HUB_FUNCTION_RUNNER_URL=http://127.0.0.1:18009 \
AGENT_HUB_IFC_SMOKE_ARTIFACT=/tmp/agent-hub-ifc-artifact.json \
uv run --package agent-hub-api pytest -q tests/integration/ifc_main_agent_test.py
docker rm -f ifc-engineering-runner
```

The optional export wraps the real calculated Workflow output in a browser API
fixture for the existing embedded App test. A sibling `.workflow.json` contains
the actual captured engineering Workflow and Run for the direct Workflow viewer
smoke test. Neither export creates a Library Artifact.

Hurdles identified:

- Runner image startup depended on source file permissions; Docker COPY now sets
  explicit readable modes for its non-root user.
- IFC geometry is insufficient to establish engineering assumptions. Missing
  inputs need a visible review step; the sample Function represents this in metadata.
- Fixed: saved single MCP Workflow outputs now open through **Final outputs →
  Open App** with captured inputs/results and the same sandbox, CSP and expansion
  controls as Artifact Apps. Loading checks Project access, current enablement,
  the captured Plugin version and the tool's reviewed UI resource. No tool runs
  or Artifact writes occur when opening the App.
- Full Workflow outputs, including IFC text, intentionally remain available for
  inspection, downstream steps and approved file updates. Metadata is a separate
  overlay; it is not yet written into the returned IFC's property sets.
- The service input limit remains 400,000 UTF-8 bytes, so this proves a small-model
  workflow, not practical large-building IFC handling.

A live-model test still requires a configured model credential.
