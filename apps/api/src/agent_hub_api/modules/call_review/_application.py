"""One user-facing plan shape across execution owners."""

from collections.abc import Mapping, Sequence

from agent_hub_api.contracts import CallReview


def call_review(
    *,
    target_kind: str,
    target_id: str,
    target_version: int | str,
    target_name: str,
    shape: str,
    source: Mapping[str, object],
    input_ports: Mapping[str, Mapping[str, object]],
    output_schema: Mapping[str, object],
    bindings: Sequence[Mapping[str, object]],
    max_invocations: int,
    output_kind: str,
) -> Mapping[str, object]:
    """Capture the target, ports, source, bounds, bindings and approval rule for review."""
    review = {
        "target": {
            "kind": target_kind,
            "id": target_id,
            "version": target_version,
            "name": target_name,
        },
        "shape": shape,
        "source": dict(source),
        "inputPorts": {name: dict(schema) for name, schema in input_ports.items()},
        "outputPorts": {"result": dict(output_schema)},
        "bindings": [dict(binding) for binding in bindings],
        "invocationCount": len(bindings),
        "maxInvocations": max_invocations,
        "outputKind": output_kind,
        "agentApproval": "required",
    }
    return CallReview.model_validate(review).model_dump(by_alias=True, exclude_none=True)
