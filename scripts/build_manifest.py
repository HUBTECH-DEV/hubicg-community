#!/usr/bin/env python3
"""Build deterministic checksums for release-governance inputs."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATHS = [
    "LICENSE", "LICENSES/AGPL-3.0-only.txt", "LICENSING.md", "NOTICE",
    "THIRD_PARTY_NOTICES.md", "pyproject.toml", "src/hubicg/__init__.py",
    "src/hubicg/cli.py", "scripts/build_sbom.py",
]

def content() -> str:
    lines = []
    for relative in PATHS:
        path = ROOT / relative
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative}")
    return "\n".join(lines) + "\n"


parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
manifest = ROOT / "MANIFEST.sha256"
generated = content()
if args.check:
    if not manifest.is_file() or manifest.read_text(encoding="utf-8") != generated:
        raise SystemExit("MANIFEST.sha256 is missing or stale")
    print("manifest=valid")
else:
    manifest.write_text(generated, encoding="utf-8")
    print(f"manifest={manifest}")
