#!/usr/bin/env python3
"""Import the HubICG role library into the packaged Community library.

The source is a checkout of the repository that authors the library, with
``.promptsLibrary/library.json``, ``roles/*.json`` and ``foundations/*.json``.
Shared blocks referenced as ``{{shared:<id>}}`` are expanded so every published
role is self-contained. Output is deterministic: the same source revision
produces the same bytes.

Usage: python scripts/import_role_library.py SOURCE --repository OWNER/NAME
       --revision SHA --version X.Y.Z
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hubicg.role_schema import validate_foundation, validate_role  # noqa: E402
TARGET = ROOT / "src" / "hubicg" / "library"
SHARED = re.compile(r"\{\{shared:([a-z0-9]+(?:-[a-z0-9]+)*)\}\}")
LOCALE = "pt-BR"


def encode(data: object) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def expand(text: str, shared: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in shared:
            raise SystemExit(f"unknown shared block: {key}")
        return shared[key]

    return SHARED.sub(replace, text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    library = args.source / ".promptsLibrary"
    skeleton = json.loads((library / "library.json").read_text(encoding="utf-8"))
    shared = {block["id"]: block["text"] for block in skeleton.get("sharedBlocks", [])}

    # Build and validate everything in memory first: a bad source must leave
    # the current library untouched, never deleted or half rebuilt.
    files: dict[str, bytes] = {}
    errors: list[str] = []
    entries: dict[str, list[dict[str, str]]] = {"roles": [], "foundations": []}

    for path in sorted((library / "foundations").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        errors += [f"{path.name}: {error}" for error in validate_foundation(data)]
        relative = f"foundations/{path.name}"
        files[relative] = encode(data)
        entries["foundations"].append(
            {"id": data["id"], "path": relative, "sha256": hashlib.sha256(files[relative]).hexdigest()}
        )

    for path in sorted((library / "roles").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schemaVersion") != "2.0":
            raise SystemExit(f"{path.name}: only contract 2.0 roles are published")
        data["lead"] = expand(data["lead"], shared)
        data["blocks"] = [
            {"heading": block["heading"], "body": expand(block["body"], shared)}
            for block in data["blocks"]
        ]
        data["locale"] = LOCALE
        errors += [f"{path.name}: {error}" for error in validate_role(data)]
        relative = f"roles/{path.name}"
        files[relative] = encode(data)
        entries["roles"].append(
            {"id": data["id"], "path": relative, "sha256": hashlib.sha256(files[relative]).hexdigest()}
        )

    known = {entry["id"] for entry in entries["foundations"]}
    for relative, payload in files.items():
        if relative.startswith("roles/"):
            unknown = sorted(set(json.loads(payload)["foundations"]) - known)
            if unknown:
                errors.append(f"{relative}: composes unknown foundations: {', '.join(unknown)}")
    if errors:
        raise SystemExit("source library is invalid; nothing was written:\n" + "\n".join(errors))

    manifest = {
        "schemaVersion": "1.0",
        "library": "hubicg-role-library",
        "version": args.version,
        "license": "AGPL-3.0-only",
        "locale": LOCALE,
        "source": {
            "repository": args.repository,
            "revision": args.revision,
            "paths": [
                ".promptsLibrary/library.json",
                ".promptsLibrary/roles/",
                ".promptsLibrary/foundations/",
            ],
        },
        "counts": {name: len(items) for name, items in entries.items()},
        **entries,
    }
    files["manifest.json"] = encode(manifest)
    if TARGET.exists():
        shutil.rmtree(TARGET)
    for relative, payload in files.items():
        (TARGET / relative).parent.mkdir(parents=True, exist_ok=True)
        (TARGET / relative).write_bytes(payload)
    print(
        f"library={TARGET.relative_to(ROOT).as_posix()} version={args.version} "
        f"roles={len(entries['roles'])} foundations={len(entries['foundations'])}"
    )


if __name__ == "__main__":
    main()
