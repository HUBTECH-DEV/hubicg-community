#!/usr/bin/env python3
"""Validate the P0 marks and provenance publication gates."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKS = ROOT / ".hubicg/gates/p0-marks.json"
PROVENANCE = ROOT / ".hubicg/gates/p0-provenance.json"
MAINTAINERS = ROOT / ".hubicg/gates/p0-maintainers.json"
REQUIRED_FIELDS = {
    "path", "sha256", "origin", "source_commit", "author",
    "classification", "license", "decision", "reviewer", "evidence",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def tracked_paths(manifest: str) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return {path for path in result.stdout.splitlines() if path and path != manifest}


def valid_review_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def validate_structure(document: dict, gate: str, errors: list[str]) -> None:
    if document.get("schemaVersion") != "1.0":
        errors.append(f"{gate}: schemaVersion must be 1.0")
    if document.get("gate") != gate:
        errors.append(f"{gate}: gate identifier mismatch")
    if document.get("owner") != "Paulo Cesar Benjamin Junior":
        errors.append(f"{gate}: owner must be Paulo Cesar Benjamin Junior")
    if document.get("status") not in {"pending", "approved", "rejected", "blocked"}:
        errors.append(f"{gate}: invalid status")


def validate_closed_marks(document: dict, errors: list[str]) -> None:
    if document.get("status") != "approved":
        errors.append("p0-marks: status is not approved")
    if not valid_review_date(document.get("reviewedAt")):
        errors.append("p0-marks: reviewedAt is missing or invalid")
    if not document.get("approvedBaseline"):
        errors.append("p0-marks: approvedBaseline is missing")
    marks = document.get("marks")
    if not isinstance(marks, list) or {item.get("name") for item in marks if isinstance(item, dict)} != {"HubTech", "HubICG"}:
        errors.append("p0-marks: HubTech and HubICG entries are required")
        return
    for mark in marks:
        name = mark.get("name", "unknown")
        if not mark.get("territories") or not mark.get("classes"):
            errors.append(f"p0-marks: {name} territories/classes are incomplete")
        if len(mark.get("searches", [])) < 4 or not mark.get("evidence"):
            errors.append(f"p0-marks: {name} search evidence is incomplete")
        if mark.get("collisionAssessment") in {None, "", "pending"}:
            errors.append(f"p0-marks: {name} collision assessment is pending")
        if mark.get("riskDecision") not in {"clear", "accepted", "mitigated"}:
            errors.append(f"p0-marks: {name} risk decision is invalid")


def validate_closed_provenance(document: dict, errors: list[str]) -> None:
    if document.get("status") != "approved":
        errors.append("p0-provenance: status is not approved")
    if not valid_review_date(document.get("reviewedAt")):
        errors.append("p0-provenance: reviewedAt is missing or invalid")
    if not document.get("approvedBaseline"):
        errors.append("p0-provenance: approvedBaseline is missing")
    for field in ("aliasesConfirmed", "thirdPartyNoticesConfirmed", "sensitiveContentReviewConfirmed"):
        if document.get(field) is not True:
            errors.append(f"p0-provenance: {field} is not confirmed")
    mailmap = ROOT / str(document.get("mailmap", ""))
    if not mailmap.is_file() or not mailmap.read_text(encoding="utf-8").strip():
        errors.append("p0-provenance: .mailmap is missing or empty")
    manifest_name = str(document.get("manifest", ""))
    manifest = ROOT / manifest_name
    if not manifest.is_file():
        errors.append("p0-provenance: manifest is missing")
        return
    with manifest.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not REQUIRED_FIELDS.issubset(reader.fieldnames or []):
            errors.append("p0-provenance: manifest columns are incomplete")
            return
        rows = list(reader)
    expected = tracked_paths(manifest_name)
    actual = {row["path"] for row in rows}
    if actual != expected:
        errors.append("p0-provenance: manifest does not cover the tracked baseline")
    for row in rows:
        path = ROOT / row["path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            errors.append(f"p0-provenance: stale or missing file {row['path']}")
        if row["decision"] != "approved" or not all(row[field] for field in REQUIRED_FIELDS):
            errors.append(f"p0-provenance: unapproved or incomplete row {row['path']}")


parser = argparse.ArgumentParser()
parser.add_argument("--require-closed", action="store_true")
args = parser.parse_args()
errors: list[str] = []
marks = load(MARKS)
provenance = load(PROVENANCE)
maintainers = load(MAINTAINERS)
validate_structure(marks, "p0-marks", errors)
validate_structure(provenance, "p0-provenance", errors)
validate_structure(maintainers, "p0-maintainers", errors)
if args.require_closed:
    validate_closed_marks(marks, errors)
    validate_closed_provenance(provenance, errors)
    if maintainers.get("status") != "approved":
        errors.append("p0-maintainers: status is not approved")
    if maintainers.get("approvedMaintainers") != ["paullobenjamin"]:
        errors.append("p0-maintainers: Paulo must be the sole approved maintainer")
    if maintainers.get("unauthorizedMaintainers"):
        errors.append("p0-maintainers: unauthorized maintainers remain")
if errors:
    for error in errors:
        print(f"gate_error={error}")
    raise SystemExit(1)
print(
    "p0_gates=valid "
    f"marks={marks['status']} provenance={provenance['status']} "
    f"maintainers={maintainers['status']}"
)
