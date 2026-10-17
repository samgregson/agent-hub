# CalculationSourceObject Plugin

This reviewed FastMCP Plugin runs one CalculationSourceObject Python source and provides a read-only MCP App report for its saved Tool Result Snapshot.

## Run locally

From the repository root:

```sh
docker compose up --build calculation-source-object
```

The service is available to Agent Hub at `http://calculation-source-object:8000/mcp` and locally at `http://localhost:8003/mcp`.

Enable **Calculation Source Object** for a Project. An agent can call `run_calculation` with:

- `source`: the complete `.cso.py` source as text, supplied directly or from a Project File through a Workflow binding;
- `function`: the decorated calculation function name;
- `inputs`: finite numeric values keyed by the declared parameter names.

The Plugin captures the source, inputs, source hash and CalculationSourceObject execution record. Agent Hub stores successful structured results using its Tool Result Snapshot policy. Opening that Artifact loads the bundled `@cs-object/react` MCP App, which renders the prepared calculation report and the captured source.

The first version accepts one source file. Calculations that depend on adjacent source modules or local figure assets are not yet supported. The report is read-only. Re-run the tool with changed inputs or source to create another result.

## Execution boundary

The server pins `cs-object==0.1.1` and verifies the downloaded wheel checksum during image build. A Deno subprocess runs Pyodide with network, environment, process execution and FFI access denied. The Plugin enforces source, input, output and execution-time bounds; Compose also runs the service read-only, without Linux capabilities, with a non-root user and CPU, memory and process limits.

The report shows captured execution only. Formula consistency and independent reference checks are not run, and the report does not establish engineering suitability or approval.
