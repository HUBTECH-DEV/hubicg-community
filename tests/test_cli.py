import json
import os
import subprocess
import sys
from pathlib import Path


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


def test_proposal_requires_exact_approval(tmp_path: Path) -> None:
    root = project(tmp_path)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({"schemaVersion": "1.0", "enabled": True}), encoding="utf-8")
    proposed = run(root, "--json", "config", "propose", str(candidate))
    proposal_id = json.loads(proposed.stdout)["proposalId"]
    assert run(root, "config", "apply", "--approval", "deadbeef").returncode == 3
    assert run(root, "config", "apply", "--approval", proposal_id).returncode == 0
    assert json.loads((root / ".hubicg" / "config.json").read_text())["enabled"] is True


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
