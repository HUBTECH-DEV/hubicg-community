#!/usr/bin/env python3
"""Build twice with a fixed epoch and require byte-identical artifacts."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path


root = Path(__file__).resolve().parents[1]
epoch = os.environ.get("SOURCE_DATE_EPOCH")
if not epoch:
    result = subprocess.run(["git", "log", "-1", "--format=%ct"], cwd=root, capture_output=True, text=True, check=True)
    epoch = result.stdout.strip()
environment = {**os.environ, "SOURCE_DATE_EPOCH": epoch}

with tempfile.TemporaryDirectory(prefix="hubicg-reproducible-") as temporary:
    outputs = [Path(temporary) / "first", Path(temporary) / "second"]
    for output in outputs:
        output.mkdir()
        subprocess.run(
            [sys.executable, "-m", "build", "--outdir", str(output)],
            cwd=root, env=environment, check=True, capture_output=True, text=True,
        )
        for sdist in output.glob("*.tar.gz"):
            subprocess.run(
                [sys.executable, str(root / "scripts/normalize_sdist.py"), str(sdist), "--epoch", epoch],
                cwd=root, env=environment, check=True, capture_output=True, text=True,
            )
    first = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in outputs[0].iterdir()}
    second = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in outputs[1].iterdir()}
    if first != second:
        raise SystemExit(f"release build is not reproducible: first={first} second={second}")
print(f"reproducible_build=valid epoch={epoch} artifacts={len(first)}")
