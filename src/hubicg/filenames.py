"""Portable and privacy-aware filename validation."""

from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any

DEFAULT_POLICY: dict[str, Any] = {
    "schemaVersion": "1.0",
    "allowedPattern": r"^[A-Za-z0-9._+@-]+$",
    "maxSegmentLength": 120,
    "maxPathLength": 240,
    "deniedTokens": [
        "cpf", "cnpj", "cnh", "passport", "password", "passwd", "secret",
        "private-key", "private_key", "id-rsa", "id_rsa", "token",
    ],
}

WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def load_policy(root: Path) -> dict[str, Any]:
    policy = dict(DEFAULT_POLICY)
    path = root / ".hubicg" / "filename-policy.json"
    if not path.is_file():
        return policy
    try:
        configured = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid filename policy: {path}: {error}") from error
    if not isinstance(configured, dict) or configured.get("schemaVersion") != "1.0":
        raise ValueError("filename policy schemaVersion must be 1.0")
    for key in ("allowedPattern", "maxSegmentLength", "maxPathLength", "deniedTokens"):
        if key in configured:
            policy[key] = configured[key]
    return policy


def repository_paths(root: Path) -> list[str]:
    """Return tracked and non-ignored candidate paths without reading contents."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root, capture_output=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is not None and result.returncode == 0:
        return sorted(item.decode("utf-8", "surrogateescape") for item in result.stdout.split(b"\0") if item)

    excluded = {".git", ".venv", ".pytest_cache", "build", "dist", "__pycache__"}
    paths: list[str] = []
    for current, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(name for name in directories if name not in excluded and not name.endswith(".egg-info"))
        relative_dir = Path(current).relative_to(root)
        paths.extend((relative_dir / name).as_posix() for name in sorted(files))
    return paths


def validate_paths(paths: list[str], policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed = re.compile(str(policy["allowedPattern"]))
    max_segment = int(policy["maxSegmentLength"])
    max_path = int(policy["maxPathLength"])
    denied = {str(token).casefold() for token in policy["deniedTokens"]}
    casefolded: dict[str, str] = {}

    for raw_path in paths:
        path = raw_path.replace("\\", "/")
        if unicodedata.normalize("NFC", path) != path:
            errors.append(f"not NFC-normalized: {raw_path}")
        if len(path.encode("utf-8")) > max_path:
            errors.append(f"path exceeds {max_path} bytes: {raw_path}")
        parts = PurePosixPath(path).parts
        if path.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            errors.append(f"unsafe path structure: {raw_path}")
            continue
        folded_path = path.casefold()
        if folded_path in casefolded and casefolded[folded_path] != path:
            errors.append(f"case-insensitive collision: {casefolded[folded_path]} <> {path}")
        casefolded[folded_path] = path

        for part in parts:
            if len(part.encode("utf-8")) > max_segment:
                errors.append(f"segment exceeds {max_segment} bytes: {raw_path}")
            if not part.isascii() or not allowed.fullmatch(part):
                errors.append(f"non-portable characters: {raw_path}")
            if part.endswith((".", " ")):
                errors.append(f"trailing dot or space: {raw_path}")
            if part.split(".", 1)[0].upper() in WINDOWS_RESERVED:
                errors.append(f"Windows-reserved name: {raw_path}")
            stem = part.rsplit(".", 1)[0].casefold()
            tokens = {stem, *(token for token in re.split(r"[._-]+", stem) if token)}
            if tokens & denied:
                errors.append(f"sensitive filename token: {raw_path}")
    return sorted(set(errors))
