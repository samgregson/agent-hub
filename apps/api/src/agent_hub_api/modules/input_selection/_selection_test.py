import pytest

from agent_hub_api.modules.input_selection import (
    SelectionRule,
    SelectionValidationError,
    SelectionValue,
    project_value,
    select_values,
)


def test_selection_rule_preserves_source_identity_after_filter_sort_and_limit() -> None:
    source = (
        SelectionValue("first", 0, {"group": "A", "score": 1}),
        SelectionValue("second", 1, {"group": "B", "score": 9}),
        SelectionValue("third", 2, {"group": "A", "score": 3}),
    )

    selected = select_values(
        source,
        SelectionRule(
            filter_path="/group", equals="A", sort_path="/score", descending=True, limit=2
        ),
    )

    assert [(item.id, item.position, item.value) for item in selected] == [
        ("third", 2, {"group": "A", "score": 3}),
        ("first", 0, {"group": "A", "score": 1}),
    ]


def test_selection_rule_rejects_unbounded_collection() -> None:
    source = tuple(SelectionValue(str(index), index, {"score": index}) for index in range(101))

    with pytest.raises(SelectionValidationError, match="explicit limit"):
        select_values(source, SelectionRule())


def test_selection_rule_preserves_scalar_values_without_requiring_an_object_source() -> None:
    source = (
        SelectionValue("first", 0, 2),
        SelectionValue("second", 1, "checked"),
    )

    assert select_values(source, SelectionRule(limit=1)) == (source[0],)


def test_projection_uses_a_json_pointer_or_the_entire_source_value() -> None:
    value = {"items": [{"load": 2}, {"load": 4}]}

    assert project_value(value, "/items/1/load") == 4
    assert project_value(value, "") == value
    with pytest.raises(SelectionValidationError, match="JSON Pointer"):
        project_value(value, "items")
    with pytest.raises(SelectionValidationError, match="did not match"):
        project_value(value, "/missing")
