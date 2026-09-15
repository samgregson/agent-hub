import json
from pathlib import Path

from ag_ui.core import Event, RunAgentInput
from pydantic import TypeAdapter


def test_pinned_ag_ui_fixture_matches_python_contract() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[3] / "packages/contracts/fixtures/ag-ui-0.0.59.json"
    )
    fixture = json.loads(fixture_path.read_text())

    event_adapter: TypeAdapter[Event] = TypeAdapter(Event)
    events = [event_adapter.validate_python(event) for event in fixture["events"]]
    resume_input = RunAgentInput.model_validate(fixture["resumeInput"])

    assert len(events) == 9
    assert resume_input.resume is not None
    assert resume_input.resume[0].interrupt_id == "interrupt-fixture"
