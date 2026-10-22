#!/usr/bin/env python3
"""Install the built wheel in isolation and prove the minimum user journey."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("--directory", type=Path, default=Path("dist"))
parser.add_argument("--output", type=Path, default=Path("dist/SMOKE-REPORT.json"))
args = parser.parse_args()
wheels = sorted(args.directory.glob("hubicg-*.whl"))
if len(wheels) != 1:
    raise SystemExit(f"expected exactly one wheel, found {len(wheels)}")

with tempfile.TemporaryDirectory(prefix="hubicg-release-smoke-") as temporary:
    root = Path(temporary)
    installed = root / "installed"
    project = root / "project"
    roles = project / ".hubicg" / "roles"
    roles.mkdir(parents=True)
    (project / ".hubicg" / "config.json").write_text('{"schemaVersion":"1.0"}\n', encoding="utf-8")
    (roles / "release-role.json").write_text(json.dumps({
        "schemaVersion": "1.0", "id": "release-role", "name": "Release Role",
        "instructions": "Validate an isolated release journey", "locale": "en",
        "version": "1.0.0", "tags": ["release"], "capabilities": ["validation"],
        "conflictsWith": [],
    }, indent=2) + "\n", encoding="utf-8")
    candidate = project / "candidate.json"
    candidate.write_text('{"schemaVersion":"1.0","verified":true}\n', encoding="utf-8")

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "--no-compile",
         "--target", str(installed), str(wheels[0].resolve())],
        check=True, capture_output=True, text=True,
    )
    isolated_environment = {
        **os.environ, "PYTHONPATH": str(installed), "PYTHONNOUSERSITE": "1",
        "HUBICG_HOME": str(root / "machine"), "PYTHONIOENCODING": "utf-8",
    }

    steps: list[str] = []
    def run(*command: str, as_json: bool = False, label: str | None = None) -> str:
        prefix = [sys.executable, "-m", "hubicg", "--root", str(project)]
        if as_json:
            prefix.append("--json")
        result = subprocess.run(
            [*prefix, *command], check=True, capture_output=True, text=True, encoding="utf-8",
            cwd=project, env=isolated_environment,
        )
        steps.append(label or " ".join(command))
        return result.stdout

    run("validate")
    run("files", "verify")
    run("roles", "db", "init")
    run("roles", "db", "import", "--source", "project")
    selection = json.loads(run("roles", "select", "release", as_json=True))
    proposal = json.loads(run(
        "config", "propose", str(candidate), as_json=True,
        label="config propose <candidate>",
    ))
    run(
        "config", "apply", "--approval", proposal["proposalId"],
        label="config apply --approval <proposal-id>",
    )
    run("evidence", "changes", "verify")
    backup = json.loads(run("roles", "db", "backup", as_json=True))
    run(
        "roles", "db", "restore", "--approval", backup["backupId"],
        label="roles db restore --approval <backup-id>",
    )
    run("roles", "db", "export")
    run("status")

    # The official library ships inside the wheel and installs per machine.
    run("library", "verify")
    library = json.loads(run("library", "install", as_json=True))
    if (library["roles"], library["foundations"]) != (65, 17):
        raise SystemExit(f"unexpected library install: {library}")
    if not json.loads(run("library", "status", as_json=True))["current"]:
        raise SystemExit("installed library does not match the packaged manifest")
    shown = json.loads(run("library", "show", "principal-scrum-master", as_json=True))
    if not shown["foundations"]:
        raise SystemExit("installed library did not resolve foundations")

report = {
    "schemaVersion": "1.0",
    "status": "passed",
    "wheel": wheels[0].name,
    "selectedRole": selection["selected"][0]["id"],
    "library": {"version": library["version"], "roles": library["roles"], "foundations": library["foundations"]},
    "steps": steps,
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"release_smoke=valid report={args.output}")
