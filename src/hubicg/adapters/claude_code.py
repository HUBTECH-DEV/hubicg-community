"""Render a HubICG role as a Claude Code subagent file.

Pure and read-only: no filesystem access. The CLI writes the rendered output
under ``.hubicg/exports/claude-code/`` through the ``config``-style
propose/apply approval flow (see ``hubicg adapters claude-code`` in
``cli.py``). It never writes outside ``.hubicg/`` -- e.g. directly into a
project's ``.claude/agents/`` -- because ``state_path`` in ``cli.py`` refuses
any such path; getting an exported file into ``.claude/agents/`` is instead a
documented manual step (see "Activating exported agents in Claude Code" in
docs/CLI-CONTRACT.md and docs/architecture/CLAUDE-CODE-ADAPTER-STUDY.md).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

FRONTMATTER = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)
MARKER = re.compile(
    r"^# hubicg:managed role=(?P<role>[a-z0-9]+(?:-[a-z0-9]+)*) "
    r"version=(?P<version>[0-9]+(?:\.[0-9]+){0,2}) "
    r"hash=sha256:(?P<hash>[0-9a-f]{64})$",
    re.MULTILINE,
)


def content_hash(name: str, instructions: str) -> str:
    digest = hashlib.sha256(f"{name}\n{instructions}".encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def render_subagent(role: dict[str, Any]) -> str:
    """Render ``role`` (role schema v1) as Claude Code subagent markdown.

    The provenance marker is a YAML comment inside the frontmatter, not a
    leading HTML comment: Claude Code (and most frontmatter parsers) require
    the file to *start* with the ``---`` fence, so nothing can precede it.

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
        f"# hubicg:managed role={role_id} version={version} "
        f"hash={content_hash(name, instructions)}"
    )
    frontmatter = f"---\nname: {role_id}\ndescription: {description}\n{marker}\n---"
    return f"{frontmatter}\n\n{instructions}\n"


def find_conflicts(roles: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Return sorted, deduplicated pairs of role ids with a declared mutual conflict.

    Only conflicts between roles that are both present in ``roles`` are
    reported: a role's ``conflictsWith`` entry for an id outside this set is
    not this adapter's concern, since it was not selected for export.
    """
    present = {role["id"] for role in roles}
    pairs = {
        tuple(sorted((role["id"], other)))
        for role in roles
        for other in role.get("conflictsWith", [])
        if other in present
    }
    return sorted(pairs)


def parse_marker(text: str) -> dict[str, str] | None:
    """Extract the ``role``/``version``/``hash`` provenance marker, if present.

    Returns ``None`` when the file has no ``---``-fenced frontmatter starting
    on its first line, or when that frontmatter has no HubICG marker comment
    — a file without one is treated as hand-authored and must not be
    overwritten by the apply step.
    """
    frontmatter_match = FRONTMATTER.match(text)
    if not frontmatter_match:
        return None
    marker_match = MARKER.search(frontmatter_match.group("body"))
    if not marker_match:
        return None
    return marker_match.groupdict()
