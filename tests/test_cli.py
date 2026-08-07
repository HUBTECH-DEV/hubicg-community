import json
import os
import subprocess
import sys
from pathlib import Path

from hubicg.role_store import SQLiteRoleRepository


def run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    return subprocess.run(
        [sys.executable, "-m", "hubicg", "--root", str(root), *args],
        capture_output=True, text=True, env=env, check=False,
    )


def project(tmp_path: Path) -> Path:
    state = tmp_path / ".hubicg"
    (state / "roles").mkdir(parents=True)
    (state / "config.json").write_text(json.dumps({"schemaVersion": "1.0"}), encoding="utf-8")
    (state / "roles" / "one.json").write_text(json.dumps({
        "schemaVersion": "1.0", "id": "one", "name": "One", "instructions": "Be useful"
    }), encoding="utf-8")
    return tmp_path


def test_validate_and_roles(tmp_path: Path) -> None:
    root = project(tmp_path)
    assert run(root, "validate").returncode == 0
    result = run(root, "--json", "roles", "list")
    assert result.returncode == 0
    assert json.loads(result.stdout)["roles"][0]["id"] == "one"


def test_role_database_import_and_search(tmp_path: Path) -> None:
    root = project(tmp_path)
    initialized = run(root, "--json", "roles", "db", "init")
    assert initialized.returncode == 0
    assert json.loads(initialized.stdout)["status"] == "initialized"
    imported = run(root, "roles", "db", "import", "--source", "custom")
    assert imported.returncode == 0
    result = run(root, "--json", "roles", "search", "useful")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["engine"] in {"fts5", "fallback"}
    assert payload["roles"][0]["id"] == "one"
    assert payload["roles"][0]["source"] == "custom"


def test_role_search_uses_files_before_database_is_initialized(tmp_path: Path) -> None:
    root = project(tmp_path)
    result = run(root, "--json", "roles", "search", "useful")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["engine"] == "files"
    assert payload["roles"][0]["id"] == "one"


def test_role_selection_is_accent_insensitive_and_explained(tmp_path: Path) -> None:
    root = project(tmp_path)
    role = root / ".hubicg" / "roles" / "architecture.json"
    role.write_text(json.dumps({
        "schemaVersion": "1.0", "id": "solution-architecture",
        "name": "Arquitetura de Soluções", "instructions": "Definir decisões auditáveis",
        "locale": "pt-BR", "version": "1.0.0", "tags": ["architecture"],
        "capabilities": ["solution-design"], "conflictsWith": [],
    }), encoding="utf-8")
    result = run(root, "--json", "roles", "select", "arquitetura idioma:pt", "--count", "2")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["selected"][0]["id"] == "solution-architecture"
    assert payload["selected"][0]["reasons"]
    assert payload["policy"]["network"] == "disabled"


def test_role_selection_reports_declared_conflict(tmp_path: Path) -> None:
    root = project(tmp_path)
    roles = root / ".hubicg" / "roles"
    (roles / "alpha.json").write_text(json.dumps({
        "schemaVersion": "1.0", "id": "alpha", "name": "Alpha Security",
        "instructions": "security analysis", "tags": ["security"],
        "capabilities": [], "conflictsWith": ["beta"],
    }), encoding="utf-8")
    (roles / "beta.json").write_text(json.dumps({
        "schemaVersion": "1.0", "id": "beta", "name": "Beta Security",
        "instructions": "security analysis", "tags": ["security"],
        "capabilities": [], "conflictsWith": [],
    }), encoding="utf-8")
    result = run(root, "--json", "roles", "select", "security", "--count", "3")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert {item["role"] for item in payload["conflicts"]} == {"beta"}


def test_role_database_backup_export_and_approved_restore(tmp_path: Path) -> None:
    root = project(tmp_path)
    assert run(root, "roles", "db", "init").returncode == 0
    assert run(root, "roles", "db", "import", "--source", "custom").returncode == 0
    backup = run(root, "--json", "roles", "db", "backup")
    backup_id = json.loads(backup.stdout)["backupId"]
    assert run(root, "roles", "db", "import", "--source", "project").returncode == 0
    assert run(root, "roles", "db", "restore", "--approval", "deadbeef").returncode == 3
    assert run(root, "roles", "db", "restore", "--approval", backup_id).returncode == 0
    selected = json.loads(run(root, "--json", "roles", "select", "useful").stdout)
    assert selected["selected"][0]["source"] == "custom"
    exported = run(root, "--json", "roles", "db", "export")
    export_path = root / json.loads(exported.stdout)["file"]
    assert json.loads(export_path.read_text(encoding="utf-8"))["roles"][0]["id"] == "one"


def test_sqlite_wal_allows_reader_during_uncommitted_writer(tmp_path: Path) -> None:
    repository = SQLiteRoleRepository(tmp_path / "roles.db")
    repository.initialize()
    repository.upsert({
        "schemaVersion": "1.0", "id": "one", "name": "One", "instructions": "Useful"
    }, "custom")
    writer = repository.connect()
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE roles SET name = 'Pending' WHERE role_id = 'one'")
        assert repository.list()[0].name == "One"
    finally:
        writer.rollback()
        writer.close()


def test_filename_policy_rejects_non_portable_name(tmp_path: Path) -> None:
    root = project(tmp_path)
    (root / "arquivo com espaço.txt").write_text("test", encoding="utf-8")
    result = run(root, "files", "verify")
    assert result.returncode == 1
    assert "non-portable characters" in result.stderr


def test_filename_policy_accepts_portable_project(tmp_path: Path) -> None:
    root = project(tmp_path)
    assert run(root, "files", "verify").returncode == 0


def test_role_schema_rejects_invalid_identifier(tmp_path: Path) -> None:
    root = project(tmp_path)
    invalid = root / ".hubicg" / "roles" / "invalid.json"
    invalid.write_text(json.dumps({
        "schemaVersion": "1.0", "id": "Not Portable", "name": "Invalid",
        "instructions": "Invalid role identifier"
    }), encoding="utf-8")
    result = run(root, "roles", "verify")
    assert result.returncode == 1
    assert "lowercase hyphenated identifier" in result.stderr


def test_role_schema_rejects_unknown_fields(tmp_path: Path) -> None:
    root = project(tmp_path)
    invalid = root / ".hubicg" / "roles" / "unknown.json"
    invalid.write_text(json.dumps({
        "schemaVersion": "1.0", "id": "unknown", "name": "Unknown",
        "instructions": "Unknown field must not be ignored", "typo": True,
    }), encoding="utf-8")
    result = run(root, "roles", "verify")
    assert result.returncode == 1
    assert "unknown fields: typo" in result.stderr


def test_proposal_requires_exact_approval(tmp_path: Path) -> None:
    root = project(tmp_path)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({"schemaVersion": "1.0", "enabled": True}), encoding="utf-8")
    proposed = run(root, "--json", "config", "propose", str(candidate))
    proposal_id = json.loads(proposed.stdout)["proposalId"]
    assert run(root, "config", "apply", "--approval", "deadbeef").returncode == 3
    assert run(root, "config", "apply", "--approval", proposal_id).returncode == 0
    assert json.loads((root / ".hubicg" / "config.json").read_text())["enabled"] is True
    assert run(root, "evidence", "changes", "verify").returncode == 0
    evidence_files = list((root / ".hubicg" / "evidence").glob("*.json"))
    assert len(evidence_files) == 1


def test_change_evidence_detects_tampering(tmp_path: Path) -> None:
    root = project(tmp_path)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({"schemaVersion": "1.0", "enabled": True}), encoding="utf-8")
    proposal_id = json.loads(run(root, "--json", "config", "propose", str(candidate)).stdout)["proposalId"]
    assert run(root, "config", "apply", "--approval", proposal_id).returncode == 0
    evidence = next((root / ".hubicg" / "evidence").glob("*.json"))
    event = json.loads(evidence.read_text(encoding="utf-8"))
    event["afterHash"] = "0" * 64
    evidence.write_text(json.dumps(event), encoding="utf-8")
    assert run(root, "evidence", "changes", "verify").returncode == 1


def test_symlinked_role_is_ignored(tmp_path: Path) -> None:
    root = project(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (root / ".hubicg" / "roles" / "escape.json").symlink_to(outside)
    assert run(root, "roles", "verify").returncode == 0


def test_git_status_does_not_require_commits(tmp_path: Path) -> None:
    root = project(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "commit.gpgSign", "false"], cwd=root, check=True)
    assert run(root, "git", "status").returncode == 0


def test_repository_manifest_is_valid() -> None:
    root = Path(__file__).parents[1]
    assert run(root, "evidence", "verify").returncode == 0


def test_maintainer_passes_cla_gate(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"user": {
        "login": "paullobenjamin", "id": 52671870
    }}}), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "check_cla.py")],
        capture_output=True, text=True, check=False,
        env={**os.environ, "GITHUB_EVENT_PATH": str(event)},
    )
    assert result.returncode == 0
    assert "cla=valid" in result.stdout


def test_similar_login_does_not_bypass_cla_gate(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"user": {
        "login": "paullo", "id": 123
    }}}), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "check_cla.py")],
        capture_output=True, text=True, check=False,
        env={**os.environ, "GITHUB_EVENT_PATH": str(event)},
    )
    assert result.returncode != 0
    assert "CLA required" in result.stderr
