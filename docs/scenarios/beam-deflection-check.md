# Engineering end-to-end scenario: floor-beam deflection and follow-up

Tracked in [issue #42](https://github.com/samgregson/agent-hub/issues/42).

## Purpose and boundary

A structural engineer checks whether a proposed, simply supported steel floor beam meets a **project-specified imposed-load deflection limit**. The agent gathers the missing criterion, invokes a calculation Plugin, explains the result, and opens a durable calculation Artifact. The engineer changes the trial section stiffness in the Plugin's MCP App and recomputes the same Artifact. The engineer then checks a small beam schedule through a Batch Run, uses a Transform Run to filter failed checks, and traces a selected failure through two Bindings to a review note.

This is an engineering scenario **after** the general-purpose foundation acceptance milestone. It does not add structural logic to the Agent Hub core. A successful comparison means only that this stated deflection check passes under the entered model and loading. It is not a beam design approval. The single-beam check is the first delivery step; the connected batch and Binding journey is the full end-to-end behavior test.

## Test fixture

All values are synthetic, supplied for a repeatable product test. They do not prescribe loads or limits for a real project.

| Input | Value | Meaning |
| --- | ---: | --- |
| Beam | B-12 | Engineer's reference |
| Analytical span, `L` | 6.0 m | Simply supported, prismatic member |
| Imposed floor load, `q` | 3.0 kN/m² | Uniform over the contributing floor area |
| Tributary width, `b` | 3.0 m | Converts area load to line load |
| Steel elastic modulus, `E` | 210 GPa | Engineer-supplied calculation assumption |
| Initial major-axis second moment, `I` | 40 × 10⁶ mm⁴ | Trial section property supplied by engineer |
| Deflection criterion | Initially omitted | Engineer later specifies imposed-load deflection ≤ `L/360` |
| Revised `I` | 80 × 10⁶ mm⁴ | Second trial section property supplied by engineer |

The Plugin calculates `w = q × b = 9.0 kN/m = 9.0 N/mm`, then `δmax = 5wL⁴/(384EI)` for a uniform load across the full simply supported span. The criterion is `6000/360 = 16.67 mm`. Initial deflection is **18.08 mm: fails this criterion**. With revised `I`, deflection is **9.04 mm: passes this criterion**. Keep full precision for the comparison and round only for display.

## Engineer journey

1. In a Project, the engineer starts a Thread: “Check imposed-load deflection for floor beam B-12. It is simply supported over 6 m; imposed load is 3 kN/m² over a 3 m tributary width. Use E = 210 GPa and trial I = 40 × 10⁶ mm⁴.”
2. The agent identifies that the comparison limit is missing and asks for it. It does not substitute a generic span ratio or present a pass/fail answer yet.
3. The engineer replies: “Use the imposed load only and a project limit of L/360.” The agent shows the interpreted inputs and calls the catalogued beam-deflection MCP tool. The user can see the tool's pending, running, and completed states.
4. The Plugin returns structured inputs, derived line load, formula/method identity, deflection, limit, and an explicit `fails` check status. Agent Hub saves the successful Tool Result Snapshot as a Project Artifact with Plugin identity, Thread/Run provenance, and a version token. The Artifact opens in the right workspace.
5. The agent explains the narrow result: 18.08 mm exceeds 16.67 mm by 1.41 mm. It offers the approximate required stiffness for this check (**43.393 × 10⁶ mm⁴**) as a calculation, not an automatically selected section. The engineer remains responsible for checking an actual section's published property and all other design requirements.
6. In the Artifact's MCP App, the engineer changes `I` to 80 × 10⁶ mm⁴ and presses Recalculate. The same ordinary MCP tool runs with the revised inputs. Agent Hub validates and saves the new Tool Result Snapshot as the current version of **the same Artifact**, recording a direct user-action provenance entry. The App now shows 9.04 mm ≤ 16.67 mm and `passes this check`.
7. The engineer reloads the page or switches to a second Thread in the same Project. The Artifact can be found and reopened with its current inputs, result, criterion, Plugin/method version, and provenance. An unauthorized Project cannot retrieve it.

## Agent and UI behavior to verify

- **Clarification:** missing criterion or ambiguous load basis triggers a question before the calculation. The agent never invents a code requirement or labels a single check as full structural compliance.
- **Units and validation:** the Plugin accepts explicit units, normalizes them for calculation, and rejects zero/negative span, modulus, inertia, or tributary width with an actionable field error. The area-to-line-load conversion is visible.
- **Deterministic calculation:** the MCP tool owns the formula and numeric result. The agent reports the returned values; it does not calculate an authoritative answer in prose. A separate deterministic oracle verifies the fixture outputs and the equality boundary.
- **Artifact:** both the failed and passed check are successful tool results. A failed engineering criterion is stored with `fails` status; it is not treated as an MCP error. The App and generic renderer can show the canonical inputs, method, result, criterion, and warnings.
- **Revision:** recomputing from the App sends the expected Artifact version. A stale version is rejected with a reload path, and a tool error leaves the current Artifact intact.
- **Recovery:** if the tool is unavailable, the Thread shows a recoverable tool error and no new Artifact is created. Reload restores the Thread and the last saved Artifact state.
- **Scope:** the App states that bending, shear, lateral stability, vibration, connections, total-load deflection, and load derivation are outside this check. These are concrete omitted checks, not a claim that the beam is safe.

## Connected Dataset, Batch Run, Transform, and Binding journey

The engineer saves a Project Dataset named **Floor beams, trial A** with three Dataset Records. This is an explicitly saved schedule of the **original trial properties**: B-12 still has `I = 40 × 10⁶ mm⁴`, even if the engineer has already revised the separate single-beam Artifact to 80 × 10⁶ mm⁴. Each record supplies the same declared fields: `beam_ref`, `L`, `q`, `b`, `E`, `I`, and the engineer's `L/360` imposed-load criterion. The Batch Definition maps those fields to the ordinary `check_uniform_beam_deflection` MCP arguments; it does not introduce a Plugin-specific batch API.

| Source key | Span | Imposed load | Width | Initial `I` | Expected deflection | Limit | Check |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| B-12 | 6.0 m | 3.0 kN/m² | 3.0 m | 40 × 10⁶ mm⁴ | 18.08 mm | 16.67 mm | Fails |
| B-13 | 5.0 m | 2.5 kN/m² | 3.0 m | 40 × 10⁶ mm⁴ | 7.27 mm | 13.89 mm | Passes |
| B-14 | 7.0 m | 3.0 kN/m² | 3.0 m | 100 × 10⁶ mm⁴ | 13.40 mm | 19.44 mm | Passes |

1. The agent proposes saving the Dataset and Batch Definition, shows the three records and field mapping, and asks for approval. It then proposes starting a Batch Run; the engineer approves the captured selection. A direct user start would use the same Batch Run operation without a second approval.
2. The host snapshots the three records, mapping, tool identity, schemas, and initiator. It invokes one real record first as the guard, then dispatches the rest within the configured bound. The UI shows durable progress and a Result Set summary: **3 completed, 1 fails the engineering criterion, 0 tool errors**. The engineer can inspect each Result Record without receiving three automatic Artifacts or a transcript dump.
3. The engineer asks, “Show me only beams that failed this check.” The agent proposes a **Transform Definition** whose declared input is the immutable Result Set snapshot and whose declared output is a bounded list of failed records. Its reviewed Python source filters records where the **engineering check status** is `fails`, retaining each host-issued Result Record ID, source key, normalized check context, and result; it does not treat tool errors as failed beam checks. After approval, a host-owned Transform Run executes against that snapshot. The output contains **B-12 only**. The engineer explicitly saves the transformed output as a Project Artifact named **Failed floor-beam checks**; the transient Transform output does not become an Artifact merely by being previewed.
4. From the failed-check Artifact, the engineer selects B-12. The agent proposes two Project Bindings as a displayed chain. The engineer reviews the exact source selectors, target arguments, cardinality, and **Ask** propagation policy, then confirms both Bindings:

   ```text
   Failed-check Artifact: selected B-12 sizing context
     -- Binding 1: one selected object -> one invocation --> size_for_deflection.input
   Required-stiffness Tool Result Snapshot: structured sizing result
     -- Binding 2: scalar/object -> one invocation --> draft_review_note.sizing_result
   ```

5. On execution, Binding 1 passes the selected failed record's declared `w`, `L`, `E`, and limit values to `size_for_deflection`. The tool returns approximately **43.393 × 10⁶ mm⁴** as the minimum inertia for this one check, plus its method and input snapshot. This is a successful MCP result and becomes an Artifact. It does not select a catalogue section.
6. Binding 2 passes the complete structured sizing result into `draft_review_note`, which produces a concise, structured note: B-12 failed the imposed-load deflection criterion at the trial `I`; the calculated minimum is approximately 43.393 × 10⁶ mm⁴; the engineer must select and verify an actual section and complete the other checks. Its successful result becomes another Artifact linked through host provenance to the failed-check Artifact, source Result Record, and sizing Artifact.
7. The host shows the bounded two-step cascade before execution and requests the decision required by each Binding's Ask policy. A single approval can cover the displayed bounded cascade. If either target expands beyond what was shown, it stops for another decision. The dataflow inspector shows `Dataset -> Batch Run -> Result Set -> Transform Run -> failed-check Artifact -> sizing Artifact -> review-note Artifact`, with the two Binding edges and their cardinalities. The engineer can reopen all records after reload.

This chain intentionally continues from **one selected failed record in the transformed Artifact**, rather than broadcasting one Result Set through several downstream batches. Filtering is a Transform; each Binding only assigns a selected structured value to a declared target argument. Bulk-to-bulk bindings are deferred by the current architecture. The Batch Run remains an immutable execution snapshot; changing the Dataset, Transform Definition, or a Binding later does not silently rewrite its Result Set or downstream Artifacts.

### Connected-flow acceptance checks

- The Batch Run invokes only a catalogued repeat-safe tool. A first-record tool/schema failure stops dispatch; a later record failure yields a visibly partial Result Set. An engineering `fails` status counts as a completed result, not a tool failure.
- The Transform Run reads the captured Result Set, records its input hash and runtime/source identity, and returns B-12 alone. A no-failure Result Set gives an empty valid output and no downstream Binding invocation. Tool errors remain separately visible. The Transform has no Project storage, secret, network, or Plugin credential access.
- The transformed output has an explicit save step and provenance. Previewing it does not create an Artifact; only the saved Artifact supplies the source value for Binding 1.
- The Batch Definition and both Bindings validate selected JSON paths against declared MCP schemas. Resolved arguments validate against each target tool's ordinary `inputSchema`. No implicit unit conversion, JSON parsing code, or hidden value inference occurs in a Binding.
- The selected B-12 object from the failed-check Artifact is the only source for Binding 1. B-13 and B-14 produce no sizing or review-note invocation. Host-issued Dataset and Result Record identities remain distinguishable from the human source key.
- Agent-proposed Dataset saves, Batch Run starts, Transform Definition/Run, transformed-output save, and Binding creation require the specified approval. A repeated approval/resume does not duplicate the Batch Run, Transform Run, or cascade invocations. Binding propagation follows the confirmed Ask policy.
- A changed source, changed Binding, stale target version, cycle, or incompatible schema is visible before execution and cannot silently overwrite a target. Every downstream result retains its source snapshot, Plugin/tool version, Binding identity, and cascade provenance.
- A browser disconnect does not abandon or duplicate the Batch Run. Completed Result Sets remain queryable; downstream Binding execution has its own explicit outcome and can be inspected after reload.

## Delivery steps

1. **Single-beam slice:** one portable `check_uniform_beam_deflection` tool and MCP App prove clarification, calculation, Artifact persistence, and user revision.
2. **Batch slice:** mark that same ordinary tool repeat-safe, add the three-record Dataset/Batch Definition fixture, and verify Batch Run and Result Set behavior.
3. **Transform slice:** add the failed-check Transform Definition and Run, with explicit Artifact save and a verified empty-result case.
4. **Binding-chain slice:** add deterministic `size_for_deflection` and `draft_review_note` tools with declared schemas, then run the selected-record chain and its approval, staleness, and provenance checks. The latter tool drafts an inspectable note; it does not approve a design or publish externally.

Agent Hub owns Dataset, Batch Run, Result Set, Transform Definition/Run, Binding, authorization, provenance, and orchestration. Plugins own the engineering calculation and note payloads and remain usable as ordinary MCP tools in a standard client. Section-catalog search, code selection, load-combination generation, diagramming, bulk-to-bulk execution, and a general calculation engine remain separate later work.

## Basis for the scenario

- [Steel Construction Institute, *Handbook of Structural Steelwork*, beam formulae](https://www.steelconstruction.info/images/6/65/Handbook_of_Structural_Steelwork_EE_55-13.pdf) gives the simply supported, uniformly loaded beam case.
- [Steel Construction Institute, *Detailed Design of Multi-Storey Buildings*, worked example A.1](https://steelconstruction.info/images/0/01/SBE_MS4.pdf) includes a serviceability deflection calculation with `5wL⁴/(384EI)` and treats serviceability separately from strength checks.
- [Steel Construction Institute, Eurocodes in the UK](https://steelconstruction.info/topics/design/design-codes-and-standards) describes serviceability verification as one part of structural design. The `L/360` value above is a **test input from the engineer**, not a criterion asserted by these sources.
