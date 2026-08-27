"""Render a HubICG role as a Claude Code subagent file.

Pure and read-only: no filesystem access. Writing the rendered file under
``.claude/agents/`` and the propose/apply approval flow are a separate,
later increment (see docs/architecture/CLAUDE-CODE-ADAPTER-STUDY.md).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

MARKER = re.compile(
    r"^<!-- hubicg:managed role=(?P<role>[a-z0-9]+(?:-[a-z0-9]+)*) "
    r"version=(?P<version>[0-9]+(?:\.[0-9]+){0,2}) "
    r"hash=sha256:(?P<hash>[0-9a-f]{64}) -->$"
)


def content_hash(name: str, instructions: str) -> str:
    digest = hashlib.sha256(f"{name}\n{instructions}".encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def render_subagent(role: dict[str, Any]) -> str:
    """Render ``role`` (role schema v1) as Claude Code subagent markdown.

    The description is built only from ``tags``/``capabilities`` because
    those fields are already restricted to the role-id slug pattern by the
    schema, so no YAML escaping is needed in the frontmatter.
    """
    role_id = role["id"]
    name = role["name"]
    instructions = role["instructions"]
    version = role.get("version", "1")
    description = ", ".join([*role.get("tags", []), *role.get("capabilities", [])]) or role_id
    marker = (
        f"<!-- hubicg:managed role={role_id} version={version} "
        f"hash={content_hash(name, instructions)} -->"
    )
    frontmatter = f"---\nname: {role_id}\ndescription: {description}\n---"
    return f"{marker}\n{frontmatter}\n\n{instructions}\n"


def parse_marker(text: str) -> dict[str, str] | None:
    """Extract the ``role``/``version``/``hash`` provenance marker, if present.

    Returns ``None`` for text with no marker or a marker on a line other than
    the first — a file without a leading HubICG marker is treated as
    hand-authored and must not be overwritten by the future apply step.
    """
    first_line = text.split("\n", 1)[0]
    match = MARKER.fullmatch(first_line)
    if not match:
        return None
    return match.groupdict()
