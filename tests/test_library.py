"""Packaged role library, role-v2 contract and the machine-wide database."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from hubicg import library
from hubicg.adapters.claude_code import render_subagent
from hubicg.role_schema import role_text, validate_foundation, validate_role

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "src" / "hubicg" / "library"


def run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-m", "hubicg", "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", env=env, check=False,
    )


def project(tmp_path: Path) -> Path:
    state = tmp_path / ".hubicg"
    (state / "roles").mkdir(parents=True)
    (state / "config.json").write_text(json.dumps({"schemaVersion": "1.0"}), encoding="utf-8")
    return tmp_path


def v2_role(**overrides: object) -> dict:
    role = {
        "schemaVersion": "2.0", "id": "example", "name": "Example", "roleVersion": "2.0.0",
        "foundations": ["research-evidence"],
        "proficiency": [{"tool": "Search", "level": "P3", "scope": "Primary sources."}],
        "blocks": [{"heading": "When to use", "body": "Use for examples."}],
    }
    role.update(overrides)
    return role


def test_packaged_library_is_complete_and_verified() -> None:
    manifest, digest, roles, foundations, errors = library.load_packaged()
    assert errors == []
    assert (len(roles), len(foundations)) == (65, 17)
    assert manifest["counts"] == {"roles": 65, "foundations": 17}
    assert manifest["license"] == "AGPL-3.0-only"
    assert len(digest) == 64


def test_every_packaged_file_is_listed_in_the_manifest() -> None:
    manifest = json.loads((LIBRARY / "manifest.json").read_text(encoding="utf-8"))
    listed = {entry["path"] for kind in ("roles", "foundations") for entry in manifest[kind]}
    on_disk = {path.relative_to(LIBRARY).as_posix() for path in LIBRARY.rglob("*.json")} - {"manifest.json"}
    assert listed == on_disk


def test_published_roles_are_self_contained() -> None:
    for path in (LIBRARY / "roles").glob("*.json"):
        assert "{{shared:" not in path.read_text(encoding="utf-8"), path.name


def test_role_v2_contract_is_enforced() -> None:
    assert validate_role(v2_role()) == []
    assert validate_role(v2_role(foundations=[]))
    assert validate_role(v2_role(proficiency=[{"tool": "x", "level": "P9", "scope": "y"}]))
    assert validate_role(v2_role(blocks=[{"heading": "only heading"}]))
    assert validate_role(v2_role(instructions="v1 field"))
    assert validate_role({**v2_role(), "schemaVersion": "3.0"})


def test_validator_accepts_every_role_the_public_schema_accepts() -> None:
    # The schema bounds each block, not their sum; the validator must not add
    # an undeclared aggregate limit and refuse a role the contract allows.
    large = v2_role(blocks=[{"heading": f"Part {index}", "body": "x" * 20_000} for index in range(6)])
    assert validate_role(large) == []


def test_role_v1_is_still_accepted() -> None:
    assert validate_role({"schemaVersion": "1.0", "id": "one", "name": "One", "instructions": "x"}) == []


def test_foundation_contract_is_enforced() -> None:
    foundation = json.loads((LIBRARY / "foundations" / "research-evidence.json").read_text(encoding="utf-8"))
    assert validate_foundation(foundation) == []
    assert validate_foundation({**foundation, "principles": []})
    assert validate_foundation({**foundation, "unexpected": True})


def test_role_text_covers_blocks_and_proficiency() -> None:
    text = role_text(v2_role())
    assert "When to use" in text and "Use for examples." in text and "Search (P3)" in text


def test_claude_code_adapter_renders_role_v2() -> None:
    rendered = render_subagent(v2_role())
    assert "version=2.0.0" in rendered
    assert "description: research-evidence" in rendered
    assert "Use for examples." in rendered


def test_tampered_library_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    copy = tmp_path / "library"
    (copy / "roles").mkdir(parents=True)
    (copy / "foundations").mkdir()
    for path in LIBRARY.rglob("*.json"):
        target = copy / path.relative_to(LIBRARY)
        target.write_bytes(path.read_bytes())
    tampered = copy / "roles" / "principal-scrum-master.json"
    tampered.write_bytes(tampered.read_bytes().replace(b"Scrum", b"Scrum!", 1))
    monkeypatch.setattr(library, "_packaged", lambda: copy)
    assert any("checksum mismatch" in error for error in library.load_packaged()[4])


def test_install_is_idempotent_and_links_foundations_through_json(tmp_path: Path) -> None:
    home = tmp_path / "home"
    first = run(project(tmp_path), "--home", str(home), "--json", "library", "install")
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["roles"] == 65
    second = run(tmp_path, "--home", str(home), "--json", "library", "install")
    assert json.loads(second.stdout)["removed"] == []

    with sqlite3.connect(home / "library.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM roles WHERE source = 'official'").fetchone()[0] == 65
        assert connection.execute("SELECT COUNT(*) FROM foundations").fetchone()[0] == 17
        linked = connection.execute(
            "SELECT foundation_id FROM role_foundations WHERE role_id = ? ORDER BY position",
            ("principal-scrum-master",),
        ).fetchall()
    assert [row[0] for row in linked][:2] == ["flow-delivery", "people-teams"]

    status = json.loads(run(tmp_path, "--home", str(home), "--json", "library", "status").stdout)
    assert status["current"] is True and status["installed"]["foundations"] == 17


def test_show_resolves_foundations_in_declared_order(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = project(tmp_path)
    assert run(root, "--home", str(home), "library", "install").returncode == 0
    shown = json.loads(run(root, "--home", str(home), "--json", "library", "show", "principal-tech-lead").stdout)
    assert [item["id"] for item in shown["foundations"]] == shown["role"]["foundations"]
    missing = run(root, "--home", str(home), "library", "show", "does-not-exist")
    assert missing.returncode == 1


def test_selection_uses_the_machine_library_with_project_precedence(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = project(tmp_path)
    assert run(root, "--home", str(home), "library", "install").returncode == 0

    official = json.loads(run(root, "--home", str(home), "--json", "roles", "select", "scrum").stdout)
    assert official["selected"][0]["id"] == "principal-scrum-master"
    assert official["selected"][0]["source"] == "official"

    by_foundation = json.loads(
        run(root, "--home", str(home), "--json", "roles", "select", "fundamento:learning-design", "--count", "5").stdout
    )
    assert {role["id"] for role in by_foundation["selected"]} == {
        "principal-pedagogy-and-didactics-specialist", "principal-didactic-presentation-designer",
    }

    (root / ".hubicg" / "roles" / "principal-scrum-master.json").write_text(json.dumps({
        "schemaVersion": "1.0", "id": "principal-scrum-master", "name": "Local Scrum", "instructions": "scrum local",
    }), encoding="utf-8")
    local = json.loads(run(root, "--home", str(home), "--json", "roles", "select", "scrum").stdout)
    assert local["selected"][0]["source"] == "project"


def test_search_never_announces_an_official_role_the_project_shadows(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = project(tmp_path)
    assert run(root, "--home", str(home), "library", "install").returncode == 0
    before = json.loads(run(root, "--home", str(home), "--json", "roles", "search", "retrospectivas").stdout)
    assert "principal-scrum-master" in {role["id"] for role in before["roles"]}

    (root / ".hubicg" / "roles" / "principal-scrum-master.json").write_text(json.dumps({
        "schemaVersion": "1.0", "id": "principal-scrum-master", "name": "Local", "instructions": "unrelated",
    }), encoding="utf-8")
    after = json.loads(run(root, "--home", str(home), "--json", "roles", "search", "retrospectivas").stdout)
    assert "principal-scrum-master" not in {role["id"] for role in after["roles"]}


def test_machine_directory_link_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("creating symbolic links needs a privilege this environment lacks")
    result = run(project(tmp_path / "p"), "--home", str(link), "library", "install")
    assert result.returncode == 1
    assert not (target / "library.db").exists()


def test_reported_database_path_is_resolved(tmp_path: Path) -> None:
    home = tmp_path / "a" / ".." / "home"
    installed = json.loads(run(project(tmp_path), "--home", str(home), "--json", "library", "install").stdout)
    assert Path(installed["database"]) == (tmp_path / "home").resolve() / "library.db"


def test_selection_without_library_is_unchanged(tmp_path: Path) -> None:
    root = project(tmp_path)
    result = json.loads(run(root, "--home", str(tmp_path / "empty"), "--json", "roles", "select", "scrum").stdout)
    assert result["selected"] == []
    assert not (tmp_path / "empty").exists(), "selection must never create the machine database"


def test_project_role_shadowing_an_official_id_is_not_overwritten(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repository = library.LibraryRepository(home / "library.db")
    repository.initialize()
    repository.upsert({"schemaVersion": "1.0", "id": "principal-scrum-master", "name": "Mine", "instructions": "x"}, "custom")
    manifest, digest, roles, foundations, _ = library.load_packaged()
    result = repository.install(manifest, digest, roles, foundations)
    assert result["skipped"] == ["principal-scrum-master"]
    assert repository.show("principal-scrum-master")["source"] == "custom"
