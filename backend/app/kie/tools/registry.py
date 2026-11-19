"""Closed tool allow-list with schema validation and access levels.

The model can only reach tools that are registered here, and the registry — not the
model — decides whether the call is well-formed and permitted. ``jsonschema`` is not a
project dependency, so the subset KIE emits (objects, primitives, arrays, enums,
required, bounds, ``additionalProperties: false``) is validated by hand in ~90 lines.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from app.kie.contracts import Access, ToolCall, ToolSpec
from app.kie.errors import ToolAccessError, ToolArgumentsError, ToolNotFoundError

ToolHandler = Callable[[dict[str, Any]], Any]

_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
}


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> list[str]:
    """Validate ``arguments`` against the supported JSON-Schema subset."""

    errors: list[str] = []
    if not isinstance(arguments, dict):
        return ["arguments must be a JSON object"]
    properties: dict[str, Any] = schema.get("properties") or {}
    for name in schema.get("required") or []:
        if name not in arguments:
            errors.append(f"missing required property '{name}'")
    if schema.get("additionalProperties") is False:
        for name in arguments:
            if name not in properties:
                errors.append(f"unexpected property '{name}'")
    for name, value in arguments.items():
        spec = properties.get(name)
        if not isinstance(spec, dict):
            continue
        declared = spec.get("type")
        if declared in _JSON_TYPES:
            expected = _JSON_TYPES[declared]
            # bool is an int subclass in Python; keep the JSON meaning.
            if declared in {"integer", "number"} and isinstance(value, bool):
                errors.append(f"property '{name}' must be a {declared}, not a boolean")
                continue
            if not isinstance(value, expected):
                errors.append(f"property '{name}' must be {declared}")
                continue
        enum = spec.get("enum")
        if enum is not None and value not in enum:
            errors.append(f"property '{name}' must be one of {enum}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            minimum = spec.get("minimum")
            maximum = spec.get("maximum")
            if minimum is not None and value < minimum:
                errors.append(f"property '{name}' must be >= {minimum}")
            if maximum is not None and value > maximum:
                errors.append(f"property '{name}' must be <= {maximum}")
        if declared == "string" and isinstance(value, str):
            max_length = spec.get("maxLength")
            if max_length is not None and len(value) > int(max_length):
                errors.append(f"property '{name}' exceeds maxLength {max_length}")
    return errors


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if not spec.name or "." not in spec.name:
            raise ValueError("tool names must be namespaced, e.g. 'patron.status'")
        if spec.name in self._specs:
            raise ValueError(f"tool '{spec.name}' is already registered")
        if spec.parameters.get("type") != "object":
            raise ValueError(f"tool '{spec.name}' must declare an object parameter schema")
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def unregister(self, name: str) -> None:
        self._specs.pop(name, None)
        self._handlers.pop(name, None)

    def specs(self) -> Sequence[ToolSpec]:
        return tuple(self._specs[name] for name in sorted(self._specs))

    def get(self, name: str) -> ToolSpec:
        spec = self._specs.get(name)
        if spec is None:
            raise ToolNotFoundError(name, list(self._specs))
        return spec

    def handler(self, name: str) -> ToolHandler:
        self.get(name)
        return self._handlers[name]

    def validate(self, call: ToolCall) -> ToolSpec:
        spec = self.get(call.name)
        errors = validate_arguments(spec.parameters, call.arguments)
        if errors:
            raise ToolArgumentsError(call.name, errors)
        return spec

    def authorize(self, spec: ToolSpec, *, confirmed: bool) -> None:
        """READ is always allowed; WRITE/PRIVILEGED need an explicit confirmation."""

        if spec.access is Access.READ:
            return
        if not confirmed:
            raise ToolAccessError(
                spec.name,
                str(spec.access),
                "this tool changes state and requires an explicit confirmation",
            )

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def __len__(self) -> int:
        return len(self._specs)
