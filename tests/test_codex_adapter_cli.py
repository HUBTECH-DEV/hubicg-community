import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from hubicg.adapters.codex import parse_marker
from hubicg.cli import atomic_export_set

def run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    return subprocess.run(
        [sys.executable, "-m", "hubicg", "--root", str(root), *args],
        capture_output=True, text=True, env=env, check=False,
    )


def write_role(root: Path, **fields: object) -> None:
    role = {"schemaVersion": "1.0", "instructions": "Be useful.", **fields}
    (root / ".hubicg" / "roles" / f"{role['id']}.json").write_text(json.dumps(role), encoding="utf-8")


def project(tmp_path: Path) -> Path:
    state = tmp_path / ".hubicg"
    (state / "roles").mkdir(parents=True)
    (state / "config.json").write_text(json.dumps({"schemaVersion": "1.0"}), encoding="utf-8")
    write_role(tmp_path, id="one", name="One")
    return tmp_path


def proposal_id(root: Path) -> str:
    result = run(root, "--json", "adapters", "codex", "propose")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["proposalId"]


def propose_and_apply(root: Path) -> subprocess.CompletedProcess[str]:
    return run(root, "adapters", "codex", "apply", "--approval", proposal_id(root))


def test_diff_then_apply_writes_valid_marked_toml(tmp_path: Path) -> None:
    root = project(tmp_path)
    diff = run(root, "--json", "adapters", "codex", "diff")
    assert diff.returncode == 0
    assert json.loads(diff.stdout)["changed"] is True
    applied = propose_and_apply(root)
    assert applied.returncode == 0, applied.stderr
    exported = root / ".hubicg" / "exports" / "codex" / "one.toml"
    content = exported.read_text(encoding="utf-8")
    assert content.startswith("# hubicg:managed adapter=codex role=one ")
    assert tomllib.loads(content)["developer_instructions"] == "Be useful."


def test_apply_is_idempotent_and_diff_becomes_empty(tmp_path: Path) -> None:
    root = project(tmp_path)
    assert propose_and_apply(root).returncode == 0
    first = (root / ".hubicg" / "exports" / "codex" / "one.toml").read_bytes()
    assert propose_and_apply(root).returncode == 0
    assert (root / ".hubicg" / "exports" / "codex" / "one.toml").read_bytes() == first
    result = run(root, "--json", "adapters", "codex", "diff")
    assert json.loads(result.stdout) == {"changed": False, "diff": []}


def test_apply_rejects_wrong_approval_and_other_proposal_kind(tmp_path: Path) -> None:
    root = project(tmp_path)
    assert run(root, "adapters", "codex", "apply", "--approval", "0" * 16).returncode == 3
    other = json.loads(run(root, "--json", "adapters", "claude-code", "propose").stdout)["proposalId"]
    result = run(root, "adapters", "codex", "apply", "--approval", other)
    assert result.returncode == 3


def test_propose_rejects_conflicting_roles(tmp_path: Path) -> None:
    root = project(tmp_path)
    write_role(root, id="one", name="One", conflictsWith=["two"])
    write_role(root, id="two", name="Two", conflictsWith=["one"])
    result = run(root, "adapters", "codex", "propose")
    assert result.returncode == 1
    assert "conflicting roles" in result.stderr


def test_apply_preserves_manual_files_and_removes_only_managed_orphans(tmp_path: Path) -> None:
    root = project(tmp_path)
    assert propose_and_apply(root).returncode == 0
    export_dir = root / ".hubicg" / "exports" / "codex"
    manual = export_dir / "manual.toml"
    manual.write_text('name = "manual"\n', encoding="utf-8")
    (root / ".hubicg" / "roles" / "one.json").unlink()
    assert propose_and_apply(root).returncode == 0
    assert manual.is_file()
    assert not (export_dir / "one.toml").exists()


def test_preflight_blocks_unmanaged_collision_without_partial_writes(tmp_path: Path) -> None:
    root = project(tmp_path)
    write_role(root, id="two", name="Two")
    export_dir = root / ".hubicg" / "exports" / "codex"
    export_dir.mkdir(parents=True)
    (export_dir / "two.toml").write_text('name = "manual"\n', encoding="utf-8")
    result = run(root, "adapters", "codex", "apply", "--approval", proposal_id(root))
    assert result.returncode == 1
    assert "unmanaged Codex export" in result.stderr
    assert not (export_dir / "one.toml").exists()
    assert (export_dir / "two.toml").read_text(encoding="utf-8") == 'name = "manual"\n'


def test_atomic_export_set_restores_previous_directory_when_swap_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    export_dir = tmp_path / "codex"
    export_dir.mkdir()
    original = (
        "# hubicg:managed adapter=codex role=one version=1 hash=sha256:" + "0" * 64 + "\n"
        'name = "one"\n'
    )
    (export_dir / "one.toml").write_text(original, encoding="utf-8")
    real_replace = os.replace

    def fail_stage_swap(source: object, destination: object) -> None:
        source_path = Path(source)
        if source_path.name.startswith(".codex-stage-") and Path(destination) == export_dir:
            raise OSError("simulated directory swap failure")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_stage_swap)
    with pytest.raises(OSError, match="simulated"):
        atomic_export_set(export_dir, ".toml", {"one": original + "# changed\n"}, parse_marker)
    assert (export_dir / "one.toml").read_text(encoding="utf-8") == original
    assert sorted(path.name for path in tmp_path.iterdir()) == ["codex"]


def test_apply_records_verifiable_codex_evidence(tmp_path: Path) -> None:
    root = project(tmp_path)
    assert propose_and_apply(root).returncode == 0
    evidence = next((root / ".hubicg" / "evidence").glob("*.json"))
    assert json.loads(evidence.read_text(encoding="utf-8"))["eventType"] == "codex-export-applied"
    assert run(root, "evidence", "changes", "verify").returncode == 0
