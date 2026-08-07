#!/usr/bin/env python3
"""Build the file-by-file P0 provenance review worksheet."""

from __future__ import annotations

import argparse
import csv
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = "docs/legal/PROVENANCE-MANIFEST.csv"
FIELDS = [
    "path", "sha256", "origin", "source_commit", "author",
    "classification", "license", "decision", "reviewer", "evidence",
]


def tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return sorted({path for path in result.stdout.splitlines() if path and path != OUTPUT})


def defaults(path: str) -> tuple[str, str, str]:
    if path == "LICENSES/AGPL-3.0-only.txt":
        return "GNU/FSF canonical license text", "upstream-license-text", "AGPL-3.0-only"
    if path == "LICENSE":
        return "Project license notice", "generated-license-notice", "AGPL-3.0-only"
    return "HubICG Community release candidate", "first-party", "AGPL-3.0-only"


parser = argparse.ArgumentParser()
parser.add_argument("--approve", action="store_true")
parser.add_argument("--baseline", default="working-tree-candidate")
args = parser.parse_args()

with (ROOT / OUTPUT).open("w", encoding="utf-8", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=FIELDS)
    writer.writeheader()
    for relative in tracked_paths():
        origin, classification, license_id = defaults(relative)
        writer.writerow({
            "path": relative,
            "sha256": hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
            "origin": origin,
            "source_commit": args.baseline,
            "author": "Paulo Cesar Benjamin Junior",
            "classification": classification,
            "license": license_id,
            "decision": "approved" if args.approve else "pending",
            "reviewer": "Paulo Cesar Benjamin Junior",
            "evidence": f"git:{args.baseline}" if args.approve else "review-required",
        })

decision = "approved" if args.approve else "pending"
print(f"provenance_manifest=generated path={OUTPUT} files={len(tracked_paths())} decision={decision}")
