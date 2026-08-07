"""Append-only, hash-chained evidence for approved local changes."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def canonical(data: Any) -> bytes:
    text = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (text + "\n").encode()


def _atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True).encode())
            stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def verify_events(directory: Path) -> tuple[int, list[str]]:
    files = sorted(directory.glob("*.json")) if directory.exists() else []
    errors: list[str] = []
    previous = None
    for expected_sequence, path in enumerate(files, start=1):
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"{path}: invalid JSON: {error}")
            continue
        if not isinstance(event, dict):
            errors.append(f"{path}: event must be an object")
            continue
        claimed = event.pop("eventHash", None)
        calculated = hashlib.sha256(canonical(event)).hexdigest()
        if event.get("schemaVersion") != "1.0" or event.get("sequence") != expected_sequence:
            errors.append(f"{path}: invalid schema or sequence")
        if event.get("previousEventHash") != previous:
            errors.append(f"{path}: broken evidence chain")
        if claimed != calculated:
            errors.append(f"{path}: event hash mismatch")
        previous = claimed
    return len(files), errors


def record_config_change(
    directory: Path,
    proposal_id: str,
    before_hash: str,
    after_hash: str,
) -> Path:
    count, errors = verify_events(directory)
    if errors:
        raise ValueError("; ".join(errors))
    files = sorted(directory.glob("*.json")) if directory.exists() else []
    previous = None
    if files:
        previous = json.loads(files[-1].read_text(encoding="utf-8"))["eventHash"]
    event = {
        "schemaVersion": "1.0",
        "sequence": count + 1,
        "eventType": "configuration-applied",
        "proposalId": proposal_id,
        "beforeHash": before_hash,
        "afterHash": after_hash,
        "previousEventHash": previous,
        "recordedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    event["eventHash"] = hashlib.sha256(canonical(event)).hexdigest()
    target = directory / f"{count + 1:06d}-{proposal_id}.json"
    _atomic_json(target, event)
    return target
