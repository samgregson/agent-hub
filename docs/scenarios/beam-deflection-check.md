# Beam-check Workflow demonstration

Tracked in [issue #42](https://github.com/samgregson/agent-hub/issues/42).

## Scope

This is a small, synthetic engineering scenario for exercising the general Dataset,
Function, MCP, and Workflow features. The beam calculations live in the independently
deployable `reference-calculation` Plugin. Agent Hub remains domain-neutral and owns the
Workflow graph, approval, captured inputs, step results, and provenance.

This demonstration checks only the stated imposed-load deflection criterion for a
simply supported, prismatic beam under full-span uniform load. It is not a beam design,
section selection, or code-compliance verdict. The `L/360` criterion is a synthetic
user-supplied test value, not a recommendation.

## Fixture

The Plugin converts floor area load to line load with `w = q × b`, then calculates
`δmax = 5wL⁴/(384EI)`. It compares the full-precision result to `L/360`; rounding is for
display only.

| Beam | Span | Imposed load | Width | E | Trial I | Deflection | Limit | Check |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| B-12 | 6.0 m | 3.0 kN/m² | 3.0 m | 210 GPa | 40 × 10⁶ mm⁴ | 18.08 mm | 16.67 mm | fails |
| B-13 | 5.0 m | 2.5 kN/m² | 3.0 m | 210 GPa | 40 × 10⁶ mm⁴ | 7.27 mm | 13.89 mm | passes |
| B-14 | 7.0 m | 3.0 kN/m² | 3.0 m | 210 GPa | 100 × 10⁶ mm⁴ | 13.40 mm | 19.44 mm | passes |

For B-12, the minimum inertia for this check is approximately `43.393 × 10⁶ mm⁴`.

## Workflow shape

The user-facing Workflow is a DAG. Its data path is:

```text
Floor beams Dataset
  -> map check_uniform_beam_deflection
  -> filter_failed_checks Function (one call over the whole result collection)
  -> map size_for_deflection
  -> map draft_beam_review_note
```

The Workflow should expose the check results, filtered failures, sizing results, and
draft notes as named outputs. Each map step retains per-item inputs, outputs, and source
identity in its Workflow Run. The filter Function receives the complete `items` array;
it returns only the values needed by the sizing tool. It is an ordinary Python Function
with a declared input/output schema and can be previewed in Functions before being wired.

Its source should follow this contract:

```python
def transform(inputs, parameters):
    return [
        {
            "beam_ref": item["beam_ref"],
            "span_m": item["span_m"],
            "imposed_load_kn_m2": item["imposed_load_kn_m2"],
            "tributary_width_m": item["tributary_width_m"],
            "elastic_modulus_gpa": item["elastic_modulus_gpa"],
            "limit_mm": item["limit_mm"],
            "trial_inertia_mm4": item["inertia_mm4"],
            "trial_deflection_mm": item["maximum_deflection_mm"],
        }
        for item in inputs["items"]
        if item["check_status"] == "fails"
    ]
```

The sizing MCP tool accepts the selected check's values and returns a result shaped for
the note tool. The note is a draft for review and is not approved or published by the
Plugin. No standalone Batch Definition, Transform Run, Result Set, or reusable Binding
object is involved: mapping and connections are properties of the Workflow graph.

## User test

In a Project with the `reference-calculation` Plugin enabled, ask the agent to create a
Workflow called **Floor beam deflection review** using the three records above. Ask it to:

1. Save the beam schedule as a Dataset.
2. Create a Python Function that selects only records whose `check_status` is `fails`,
   retaining the fields needed by `size_for_deflection`.
3. Connect a mapped beam check, the collection filter, mapped sizing, and mapped note
   drafting in a DAG. Expose the four corresponding outputs.
4. Validate and preview the Function, then prepare and run the Workflow after approval.

The approval cards should describe each durable Project change and the Workflow Run.
The Workflow page should show a navigable graph. Opening a completed run should show
B-12 as the only failed record, a required inertia near `43.393 × 10⁶ mm⁴`, and one
review-only note. B-13 and B-14 must not be sized or noted. Reopening the run after
reload should preserve its captured inputs and outputs.

Invalid physical inputs return a structured invalid calculation result. A failed
engineering criterion remains a successful tool result. The agent and UI must describe
the result as `passes this check` or `fails this check`, never as a whole-beam safety
verdict. Bending strength, shear, lateral stability, vibration, connections, load
derivation, and all other design checks are outside this demonstration.
