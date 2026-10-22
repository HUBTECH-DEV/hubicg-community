"""Public artifact integrity and export preserve user files."""
import hashlib
import re
from pathlib import Path

import pytest

from scripts.build_station_agents import export, render_all
from hubicg.library import load_packaged


def test_roles_and_foundations_are_delivered():
    _, _, roles, foundations, errors = load_packaged()
    assert not errors
    rendered = render_all()
    assert set(rendered) == {f"{role['id']}.md" for role in roles}
    known = {item["id"]: item for item in foundations}
    for role in roles:
        text = rendered[f"{role['id']}.md"]
        header, body = text.split("\n---\n\n", 1)
        digest = re.search(r"hash=sha256:([a-f0-9]{64})", header)[1]
        assert digest == hashlib.sha256(body.encode()).hexdigest()
        for key in role.get("foundations", []):
            assert known[key]["guardrails"][0] in body


def test_export_is_idempotent_and_preserves_edits(tmp_path: Path):
    export(tmp_path)
    before = {path.name: path.stat().st_mtime_ns for path in tmp_path.glob("*.md")}
    export(tmp_path)
    assert before == {path.name: path.stat().st_mtime_ns for path in tmp_path.glob("*.md")}
    target = next(tmp_path.glob("*.md"))
    target.write_text("user edit", encoding="utf-8")
    with pytest.raises(ValueError, match="existing file differs"):
        export(tmp_path)
    assert target.read_text() == "user edit"


def test_unexpected_agent_is_preserved(tmp_path: Path):
    target = tmp_path / "custom.md"
    target.write_text("custom", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected agents"):
        export(tmp_path)
    assert list(tmp_path.iterdir()) == [target]
