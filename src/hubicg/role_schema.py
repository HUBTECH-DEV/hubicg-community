"""Role schema validation shared by files and the local database.

Two role contracts coexist: ``role-v1`` (``instructions`` as one text) and
``role-v2`` (structured ``blocks`` composing shared ``foundations`` and
declaring ``proficiency``). The CLI reads both; ``role_text`` gives every role
the single searchable text that selection, search and adapters consume.
"""

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
ALLOWED_FIELDS_V2 = {
    "schemaVersion", "id", "name", "area", "section", "seniority", "roleVersion",
    "extends", "foundations", "specializations", "proficiency", "lead", "blocks",
    "locale", "tags", "capabilities", "conflictsWith",
}
LEVELS = ("P0", "P1", "P2", "P3", "P4")
FOUNDATION_FIELDS = {
    "schemaVersion", "id", "name", "version", "locale", "summary", "principles",
    "practices", "theories", "lawsAndModels", "references", "guardrails",
}
FOUNDATION_LISTS = ("principles", "practices", "theories", "lawsAndModels", "references", "guardrails")


def validate_role(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["role must be an object"]
    if data.get("schemaVersion") == "2.0":
        return validate_role_v2(data)
    errors: list[str] = []
    unknown = sorted(set(data) - ALLOWED_FIELDS)
    if unknown:
        errors.append(f"unknown fields: {', '.join(unknown)}")
    if data.get("schemaVersion") != "1.0":
        errors.append("schemaVersion must be 1.0 or 2.0")
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


def _text(value: Any, limit: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _identifiers(data: dict[str, Any], field: str, pattern: re.Pattern[str], required: bool) -> list[str]:
    value = data.get(field, [])
    if not isinstance(value, list) or len(value) > 64 or (required and not value):
        size = "1 to 64" if required else "at most 64"
        return [f"{field} must be an array with {size} entries"]
    if any(not isinstance(item, str) or not pattern.fullmatch(item) for item in value):
        return [f"{field} contains an invalid identifier"]
    if len(value) != len(set(value)):
        return [f"{field} must not contain duplicates"]
    return []


def validate_role_v2(data: dict[str, Any]) -> list[str]:
    """Validate the composable role contract (``schemas/role-v2.schema.json``)."""
    errors: list[str] = []
    unknown = sorted(set(data) - ALLOWED_FIELDS_V2)
    if unknown:
        errors.append(f"unknown fields: {', '.join(unknown)}")
    role_id = data.get("id")
    if not isinstance(role_id, str) or not ROLE_ID.fullmatch(role_id):
        errors.append("id must be a lowercase hyphenated identifier")
    if not _text(data.get("name"), 120):
        errors.append("name must contain 1 to 120 characters")
    version = data.get("roleVersion")
    if not isinstance(version, str) or not ROLE_VERSION.fullmatch(version):
        errors.append("roleVersion must contain one to three numeric components")
    locale = data.get("locale", "und")
    if not isinstance(locale, str) or not LOCALE.fullmatch(locale):
        errors.append("locale must be und or a BCP-47-style language tag")
    for field in ("area", "section", "seniority", "lead"):
        if field in data and not _text(data[field], 2_000):
            errors.append(f"{field} must contain 1 to 2000 characters")
    if "extends" in data and (not isinstance(data["extends"], str) or not ROLE_ID.fullmatch(data["extends"])):
        errors.append("extends must be a lowercase hyphenated identifier")
    errors += _identifiers(data, "foundations", ROLE_ID, required=True)
    for field, pattern in (("specializations", ROLE_ID), ("conflictsWith", ROLE_ID), ("tags", TAG), ("capabilities", TAG)):
        errors += _identifiers(data, field, pattern, required=False)
    proficiency = data.get("proficiency")
    if not isinstance(proficiency, list) or not proficiency or len(proficiency) > 64:
        errors.append("proficiency must be an array with 1 to 64 entries")
    else:
        for item in proficiency:
            if (
                not isinstance(item, dict) or set(item) != {"tool", "level", "scope"}
                or item.get("level") not in LEVELS
                or not _text(item.get("tool"), 200) or not _text(item.get("scope"), 2_000)
            ):
                errors.append("proficiency entries need tool, level P0 to P4 and scope")
                break
    blocks = data.get("blocks")
    if not isinstance(blocks, list) or not blocks or len(blocks) > 64:
        errors.append("blocks must be an array with 1 to 64 entries")
    else:
        for block in blocks:
            if (
                not isinstance(block, dict) or set(block) != {"heading", "body"}
                or not _text(block.get("heading"), 200) or not _text(block.get("body"), 20_000)
            ):
                errors.append("blocks entries need a heading and a body")
                break
    return errors


def validate_foundation(data: Any) -> list[str]:
    """Validate a shared foundation (``schemas/foundation.schema.json``)."""
    if not isinstance(data, dict):
        return ["foundation must be an object"]
    errors: list[str] = []
    unknown = sorted(set(data) - FOUNDATION_FIELDS)
    if unknown:
        errors.append(f"unknown fields: {', '.join(unknown)}")
    if data.get("schemaVersion") != "2.0":
        errors.append("schemaVersion must be 2.0")
    foundation_id = data.get("id")
    if not isinstance(foundation_id, str) or not ROLE_ID.fullmatch(foundation_id):
        errors.append("id must be a lowercase hyphenated identifier")
    if not _text(data.get("name"), 120):
        errors.append("name must contain 1 to 120 characters")
    version = data.get("version")
    if not isinstance(version, str) or not ROLE_VERSION.fullmatch(version):
        errors.append("version must contain one to three numeric components")
    locale = data.get("locale", "und")
    if not isinstance(locale, str) or not LOCALE.fullmatch(locale):
        errors.append("locale must be und or a BCP-47-style language tag")
    if not _text(data.get("summary"), 2_000):
        errors.append("summary must contain 1 to 2000 characters")
    for field in FOUNDATION_LISTS:
        value = data.get(field, [])
        required = field in ("principles", "practices")
        if not isinstance(value, list) or (required and not value) or any(not _text(item, 2_000) for item in value):
            errors.append(f"{field} must be an array of non-empty strings")
    return errors


def role_text(data: dict[str, Any]) -> str:
    """Return the instruction text of a role in either contract.

    For ``role-v2`` the text is rendered from ``lead``, ``blocks`` and
    ``proficiency`` in their declared order, so search and selection see the
    same words a reader does.
    """
    if data.get("schemaVersion") != "2.0":
        return str(data.get("instructions", ""))
    parts = [str(data["lead"])] if data.get("lead") else []
    for block in data.get("blocks", []):
        if isinstance(block, dict):
            parts.append(f"## {block.get('heading', '')}\n\n{block.get('body', '')}")
    entries = [item for item in data.get("proficiency", []) if isinstance(item, dict)]
    if entries:
        lines = [f"- {item.get('tool', '')} ({item.get('level', '')}): {item.get('scope', '')}" for item in entries]
        parts.append("## Proficiency\n\n" + "\n".join(lines))
    return "\n\n".join(parts)
