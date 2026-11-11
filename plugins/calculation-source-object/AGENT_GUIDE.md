# Calculation Source Object guide

`run_calculation` executes one constrained `.cso.py` source file. Supply the
complete source text in `source`, the name of its decorated function in
`function`, and an object of finite numeric values keyed by parameter name in
`inputs`. A normal Python function is not sufficient: calculations require
`@calculation`, `@section`, annotated input and result symbols, and a final
literal dictionary of named outputs. Adjacent modules and figure assets are not
supported by this Plugin. For the full authoring language see
https://github.com/viktar-b/CalculationSourceObject/blob/main/docs/authoring.md.

For example, this complete single-file calculation returns an area:

```python
from typing import Annotated
from cso_python import calculation, section, symbol

@calculation(id="rectangle", title="Rectangle")
@section(id="geometry", title="Geometry")
def area(
    width: Annotated[float, symbol(glyph="w_{rect}", description="Width", unit="m")],
    height: Annotated[float, symbol(glyph="h_{rect}", description="Height", unit="m")],
):
    result: Annotated[float, symbol(glyph="A_{rect}", description="Area", unit="m^2")] = width * height
    return {"area": result}
```

Call with `function: "area"` and `inputs: {"width": 2, "height": 3}`. The
structured result has `outputs: {"area": 6}` and `execution` contains the full
report. Output names are defined by the source's return dictionary. Do not guess
output names or paths from the report; read `outputs` by name. The report captures
source, inputs and calculations but is not independent verification or approval.
To preview without copying source into the conversation, read the authorised
Project File with `tools.readProjectFile` inside `eval`, then call
`tools.calculationSourceObject_RunCalculation({source: file.content, function:
"area", inputs: {width: 2, height: 3}})`. The public result is in
`result.structuredContent.outputs`. This preview is transient and does not save
an Artifact. Use the normal Plugin tool or a Workflow Run to save a result.

For a reusable Workflow, bind an authorised Project File's contents to `source`.
Add a Plugin node targeting `run_calculation`; the `.cso.py` file is input to
that Plugin, not source for a host Python Function. A host Function is useful
only for separate preparation or joining of data.
Use a Function to convert arbitrary tabular data into objects shaped as
`{"inputs": {"parameter_name": 1.0}}`. For an MCP Map node, bind that array to
the node's `items` port and bind `source` and `function` as shared inputs. Each
item is merged with the shared inputs to form one complete tool call. `map_input`
is used for Python Function Map, not MCP Map. Keep
identifiers in the upstream data and join them back to results in the same order;
identifiers are not numeric calculation inputs. Map results include individual
execution records; expose these for inspection as well as downstream `outputs`.
A standalone successful tool result can be opened as a report Artifact. In a
saved Workflow Run, select a successful Map item and choose **Open MCP App** to
view its captured calculation report without rerunning the tool.

Source is limited to 64,000 UTF-8 bytes, inputs to 32,000 bytes and output to
768,000 bytes; each execution is limited to 12 seconds after it acquires the runner. On a tool
error, correct the reported source, function or inputs and retry. Do not invent
missing inputs, capacities, units or assumptions.
