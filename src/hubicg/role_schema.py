"""Role schema validation shared by files and the local database."""

from __future__ import annotations

import re
from typing import Any

ROLE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ROLE_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}$")
LOCALE = re.compile(r"^(?:und|[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)$")
TAG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_FIELDS = {
    "schemaVersion", "id", "name", "instructions", "version", "locale",
    "tags", "capabilities", "conflictsWith",
}


def validate_role(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["role must be an object"]
    errors: list[str] = []
    unknown = sorted(set(data) - ALLOWED_FIELDS)
    if unknown:
        errors.append(f"unknown fields: {', '.join(unknown)}")
    if data.get("schemaVersion") != "1.0":
        errors.append("schemaVersion must be 1.0")
    role_id = data.get("id")
    if not isinstance(role_id, str) or not ROLE_ID.fullmatch(role_id):
        errors.append("id must be a lowercase hyphenated identifier")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        errors.append("name must contain 1 to 120 characters")
    instructions = data.get("instructions")
    if not isinstance(instructions, str) or not instructions.strip() or len(instructions) > 20_000:
        errors.append("instructions must contain 1 to 20000 characters")
    version = data.get("version", "1")
    if not isinstance(version, str) or not ROLE_VERSION.fullmatch(version):
        errors.append("version must contain one to three numeric components")
    locale = data.get("locale", "und")
    if not isinstance(locale, str) or not LOCALE.fullmatch(locale):
        errors.append("locale must be und or a BCP-47-style language tag")
    for field in ("tags", "capabilities", "conflictsWith"):
        value = data.get(field, [])
        if not isinstance(value, list) or len(value) > 64:
            errors.append(f"{field} must be an array with at most 64 entries")
            continue
        if any(not isinstance(item, str) for item in value):
            errors.append(f"{field} must contain only strings")
            continue
        if len(value) != len(set(value)):
            errors.append(f"{field} must not contain duplicates")
        for item in value:
            pattern = ROLE_ID if field == "conflictsWith" else TAG
            if not isinstance(item, str) or not pattern.fullmatch(item):
                errors.append(f"{field} contains an invalid identifier")
                break
    return errors
