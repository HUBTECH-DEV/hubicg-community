from __future__ import annotations
import re
from datetime import datetime
from typing import Any
from pathlib import Path
import json
RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T"
    r"\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2})$"
)


class SchemaValidationError(RuntimeError):
    """Raised when a schema or instance violates the supported contract."""


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SchemaValidationError(f"invalid JSON {path}: {error}") from error


def matches_type(value: Any, expected: str) -> bool:
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: (
            isinstance(item, (int, float)) and not isinstance(item, bool)
        ),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if expected not in checks:
        raise SchemaValidationError(f"unsupported schema type: {expected}")
    return checks[expected](value)


def validate_datetime(value: str, location: str) -> None:
    if RFC3339_PATTERN.fullmatch(value) is None:
        raise SchemaValidationError(
            f"{location}: date-time must be complete RFC3339 with timezone"
        )
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise SchemaValidationError(
            f"{location}: invalid date-time {value!r}"
        ) from error
    if parsed.tzinfo is None:
        raise SchemaValidationError(f"{location}: date-time timezone is required")


def validate_instance(value: Any, schema: dict[str, Any], location: str = "$") -> None:
    if "const" in schema and value != schema["const"]:
        raise SchemaValidationError(
            f"{location}: expected constant {schema['const']!r}, got {value!r}"
        )
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaValidationError(
            f"{location}: value {value!r} is outside the allowed enum"
        )

    declared = schema.get("type")
    if declared is not None:
        expected_types = [declared] if isinstance(declared, str) else declared
        if not isinstance(expected_types, list) or not all(
            isinstance(item, str) for item in expected_types
        ):
            raise SchemaValidationError(f"{location}: invalid type declaration")
        if not any(matches_type(value, item) for item in expected_types):
            raise SchemaValidationError(
                f"{location}: expected type {expected_types}, "
                f"got {type(value).__name__}"
            )

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise SchemaValidationError(f"{location}: string is too short")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            raise SchemaValidationError(
                f"{location}: value does not match {pattern!r}"
            )
        if schema.get("format") == "date-time":
            validate_datetime(value, location)

    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaValidationError(
                f"{location}: value is below minimum {schema['minimum']}"
            )

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise SchemaValidationError(f"{location}: array has too few items")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                validate_instance(item, item_schema, f"{location}[{index}]")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            raise SchemaValidationError(
                f"{location}: missing required properties {missing}"
            )
        for key, item in value.items():
            child = properties.get(key)
            if child is not None:
                validate_instance(item, child, f"{location}.{key}")
            elif schema.get("additionalProperties") is False:
                raise SchemaValidationError(
                    f"{location}: unexpected property {key!r}"
                )
