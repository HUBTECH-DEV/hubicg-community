#!/usr/bin/env python3
"""Generate unsigned, hash-bound build provenance for the private candidate."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path


def revision() -> str:
    value = os.environ.get("GITHUB_SHA")
    if value:
        return value
    result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def created_at() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    value = dt.datetime.fromtimestamp(int(epoch), dt.timezone.utc) if epoch else dt.datetime.now(dt.timezone.utc)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


parser = argparse.ArgumentParser()
parser.add_argument("--directory", type=Path, default=Path("dist"))
args = parser.parse_args()
files = sorted(
    path for path in args.directory.iterdir()
    if path.is_file() and not path.is_symlink() and path.name not in {"BUILD-PROVENANCE.json", "SHA256SUMS"}
)
manifest = Path("MANIFEST.sha256")
document = {
    "schemaVersion": "1.0",
    "status": "release-candidate-unsigned",
    "version": "0.1.0",
    "revision": revision(),
    "createdAt": created_at(),
    "builder": "github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local",
    "environment": {"os": platform.system(), "python": platform.python_version()},
    "sourceManifestSha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    "artifacts": [
        {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size}
        for path in files
    ],
    "legalGate": "required-before-tag-or-public-release",
}
target = args.directory / "BUILD-PROVENANCE.json"
target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"provenance={target}")
