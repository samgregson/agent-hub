"""Rules shared by selections from Dataset and retained operation values."""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast


class SelectionValidationError(ValueError):
    """A rule or source value cannot produce a bounded selection."""


@dataclass(frozen=True, slots=True)
class SelectionValue:
    id: str
    position: int
    value: object
    source_key: str | None = None


@dataclass(frozen=True, slots=True)
class SelectionRule:
    filter_path: str | None = None
    equals: str | int | float | bool | None = None
    sort_path: str | None = None
    descending: bool = False
    limit: int | None = None

    def snapshot(self) -> Mapping[str, object]:
        return {
            "filterPath": self.filter_path,
            "equals": self.equals,
            "sortPath": self.sort_path,
            "descending": self.descending,
            "limit": self.limit,
        }


def select_values(
    values: Sequence[SelectionValue], rule: SelectionRule
) -> tuple[SelectionValue, ...]:
    """Apply an explicit rule in source order before bounded capture."""
    if rule.limit is not None and not 1 <= rule.limit <= 100:
        raise SelectionValidationError("Selection limit must be between 1 and 100.")
    for pointer in (rule.filter_path, rule.sort_path):
        if pointer is not None and (
            not pointer.startswith("/") or re.search(r"~(?![01])", pointer) is not None
        ):
            raise SelectionValidationError("Selection paths must be JSON Pointers.")
    if rule.filter_path is None and rule.equals is not None:
        raise SelectionValidationError("A filter value requires a filter path.")
    if rule.filter_path is not None:
        if rule.equals is not None and not isinstance(rule.equals, (str, int, float, bool)):
            raise SelectionValidationError("Filter equality must be a JSON scalar.")
        try:
            json.dumps(rule.equals, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise SelectionValidationError("Filter equality must be a JSON scalar.") from error
    selected = list(values)
    if rule.filter_path is not None:
        matching: list[SelectionValue] = []
        for item in selected:
            value = project_value(item.value, rule.filter_path)
            if not isinstance(value, (str, int, float, bool, type(None))):
                raise SelectionValidationError("Filter path must select a scalar value.")
            if _same_scalar(value, rule.equals):
                matching.append(item)
        selected = matching
    if rule.sort_path is not None:
        keys = [project_value(item.value, rule.sort_path) for item in selected]
        if keys and (
            any(
                isinstance(value, bool) or not isinstance(value, (str, int, float))
                for value in keys
            )
            or any(isinstance(value, str) != isinstance(keys[0], str) for value in keys)
        ):
            raise SelectionValidationError("Sort path must select comparable strings or numbers.")
        selected.sort(
            key=lambda item: cast(
                str | int | float, project_value(item.value, rule.sort_path or "")
            ),
            reverse=rule.descending,
        )
    if rule.limit is not None:
        selected = selected[: rule.limit]
    if len(selected) > 100:
        raise SelectionValidationError("Selection exceeds 100 values; add an explicit limit.")
    return tuple(selected)


def project_value(value: object, path: str) -> object:
    """Project one JSON value through an explicit JSON Pointer."""
    if path == "":
        return value
    if not path.startswith("/") or re.search(r"~(?![01])", path) is not None:
        raise SelectionValidationError("Projection path must be a JSON Pointer.")
    current: object = value
    for raw in path[1:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and key in current:
            current = current[key]
        elif isinstance(current, list) and key.isdecimal() and int(key) < len(current):
            current = current[int(key)]
        else:
            raise SelectionValidationError("Selection path did not match a source value.")
    return current


def _same_scalar(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    return type(left) is type(right) and left == right
