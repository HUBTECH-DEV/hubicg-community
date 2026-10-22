#!/usr/bin/env python3
"""Export verified public roles for the station installer (no network or login)."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hubicg.adapters.claude_code import render_subagent
from hubicg.library import load_packaged
from hubicg.role_schema import FOUNDATION_LISTS


def render_all(*, library=None) -> dict[str, str]:
    """Compose canonical roles/foundations; use the station body integrity marker."""
    _, _, roles, foundations, errors = library if library is not None else load_packaged()
    if errors:
        raise ValueError("; ".join(errors))
    known = {item["id"]: item for item in foundations}
    output = {}
    for role in roles:
        header, body = render_subagent(role).split("\n---\n\n", 1)
        for key in role.get("foundations", []):
            foundation = known[key]
            body += f"\n## {foundation['name']}\n\n{foundation['summary']}\n"
            for field in FOUNDATION_LISTS:
                if foundation.get(field):
                    body += f"\n### {field}\n\n" + "\n".join(f"- {line}" for line in foundation[field]) + "\n"
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        header = re.sub(r"hash=sha256:[0-9a-f]{64}", f"hash=sha256:{digest}", header)
        output[f"{role['id']}.md"] = header + "\n---\n\n" + body
    return output


def export(destination: Path) -> int:
    """Refuse existing differing files; never delete or replace user content."""
    library = load_packaged()
    rendered = render_all(library=library)
    metadata = json.dumps({"schema": "hubicg.station.agents-export/1",
                           "libraryManifestSha256": library[1]}, sort_keys=True) + "\n"
    receipt = destination / ".hubicg-station-export.json"
    if destination.is_symlink():
        raise ValueError(f"refusing symbolic link: {destination}")
    if receipt.is_symlink() or (receipt.exists() and receipt.read_bytes() != metadata.encode("utf-8")):
        raise ValueError("existing export belongs to another library; preserve it and choose an empty export directory")
    for name, text in rendered.items():
        path = destination / name
        if path.is_symlink() or (path.exists() and path.read_bytes() != text.encode("utf-8")):
            raise ValueError(f"existing file differs: {path}; choose an empty export directory")
    extra = set(path.name for path in destination.glob("*.md")) - set(rendered)
    if extra:
        raise ValueError("unexpected agents in export; choose an empty export directory")
    destination.mkdir(parents=True, exist_ok=True)
    for name, text in rendered.items():
        path = destination / name
        if not path.exists():
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
    if not receipt.exists():
        with receipt.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(metadata)
    return len(rendered)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".hubicg/exports/station-agents")
    args = parser.parse_args()
    try:
        count = export(args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"station agents: {error}\n")
    print(f"agents={count} source=public-library destination={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
