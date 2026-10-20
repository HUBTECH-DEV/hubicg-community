"""Public role discovery and integrity coverage."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_public_role_is_covered_by_release_manifest():
    entries = dict(line.split("  ", 1)[::-1] for line in (ROOT / "MANIFEST.sha256").read_text().splitlines())
    for role in (ROOT / ".hubicg/roles").glob("*.json"):
        assert entries[role.relative_to(ROOT).as_posix()] == hashlib.sha256(role.read_bytes()).hexdigest()


def test_promoted_roles_are_discoverable_by_cli():
    result = subprocess.run([sys.executable, "-m", "hubicg", "--root", str(ROOT), "--json", "roles", "list"], capture_output=True, text=True, encoding="utf-8", check=True)
    ids = {role["id"] for role in json.loads(result.stdout)["roles"]}
    for role in (ROOT / ".hubicg/roles").glob("*.json"):
        assert json.loads(role.read_text(encoding="utf-8"))["id"] in ids
