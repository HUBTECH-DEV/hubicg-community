"""Render HubICG roles as project-scoped Codex custom-agent TOML.

This module is pure and performs no filesystem or network access. The CLI
stages generated files below ``.hubicg/exports/codex/``. Promotion into
``.codex/agents/`` is intentionally outside this adapter's write boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

MARKER = re.compile(
    r"^# hubicg:managed adapter=codex role=(?P<role>[a-z0-9]+(?:-[a-z0-9]+)*) "
    r"version=(?P<version>[0-9]+(?:\.[0-9]+){0,2}) "
    r"hash=sha256:(?P<hash>[0-9a-f]{64})$"
)


def canonical_payload(role: dict[str, Any]) -> dict[str, Any]:
    """Return every role field that influences the rendered TOML."""
    return {
        "id": role["id"],
        "name": role["name"],
        "instructions": role["instructions"],
        "version": role.get("version", "1"),
        "tags": list(role.get("tags", [])),
        "capabilities": list(role.get("capabilities", [])),
        "locale": role.get("locale", "und"),
    }


def content_hash(role: dict[str, Any]) -> str:
    canonical = json.dumps(
        canonical_payload(role), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def codex_agent_name(role_id: str) -> str:
    """Map the role slug to the underscore convention used by Codex agents."""
    return role_id.replace("-", "_")


def toml_string(value: str) -> str:
    """Encode a string using TOML's JSON-compatible basic-string syntax.

    ``json.dumps`` escapes every control character TOML forbids unescaped in
    a basic string except U+007F (DEL): JSON's own escaping only covers
    codepoints below 0x20, so a literal DEL passes through untouched and
    ``tomllib`` then rejects it. Escape it explicitly as a TOML unicode
    escape; every other codepoint TOML forbids unescaped is already covered
    by ``json.dumps``.
    """
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def render_custom_agent(role: dict[str, Any]) -> str:
    role_id = role["id"]
    version = role.get("version", "1")
    terms = [*role.get("tags", []), *role.get("capabilities", [])]
    use_for = ", ".join(terms) if terms else role_id
    description = f"{role['name']}. Use for: {use_for}."
    marker = (
        f"# hubicg:managed adapter=codex role={role_id} version={version} "
        f"hash={content_hash(role)}"
    )
    return (
        f"{marker}\n"
        f"name = {toml_string(codex_agent_name(role_id))}\n"
        f"description = {toml_string(description)}\n"
        f"developer_instructions = {toml_string(role['instructions'])}\n"
    )


def find_conflicts(roles: list[dict[str, Any]]) -> list[tuple[str, str]]:
    present = {role["id"] for role in roles}
    pairs = {
        tuple(sorted((role["id"], other)))
        for role in roles
        for other in role.get("conflictsWith", [])
        if other in present
    }
    return sorted(pairs)


def find_name_collisions(roles: list[dict[str, Any]]) -> list[tuple[str, ...]]:
    by_name: dict[str, list[str]] = {}
    for role in roles:
        by_name.setdefault(codex_agent_name(role["id"]), []).append(role["id"])
    return sorted(tuple(sorted(ids)) for ids in by_name.values() if len(ids) > 1)


def parse_marker(text: str) -> dict[str, str] | None:
    first_line = text.split("\n", 1)[0]
    match = MARKER.fullmatch(first_line)
    return match.groupdict() if match else None
