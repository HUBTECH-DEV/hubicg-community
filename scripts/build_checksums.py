#!/usr/bin/env python3
"""Create or verify portable SHA-256 release checksums."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def checksum_content(directory: Path) -> str:
    files = sorted(
        path for path in directory.iterdir()
        if path.is_file() and not path.is_symlink() and path.name != "SHA256SUMS"
    )
    return "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in files)


parser = argparse.ArgumentParser()
parser.add_argument("--directory", type=Path, default=Path("dist"))
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
target = args.directory / "SHA256SUMS"
generated = checksum_content(args.directory)
if args.check:
    if not target.is_file() or target.read_text(encoding="utf-8") != generated:
        raise SystemExit("release checksums are missing or stale")
    print(f"checksums=valid files={len(generated.splitlines())}")
else:
    target.write_text(generated, encoding="utf-8")
    print(f"checksums={target}")
