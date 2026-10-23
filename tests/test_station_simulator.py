"""O motor simulado precisa falar exatamente o contrato hubicg.station.event/1.

As interfaces graficas sao testadas contra ele sem instalar ferramentas reais. Se a fixture
desviar do contrato, os testes das interfaces passam a provar a coisa errada; por isso cada evento e
validado contra docs/schemas/station-event.schema.json, inclusive os ramos condicionais (allOf/if/then).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.station_fakes.schema_subset import validate_instance


ROOT = Path(__file__).resolve().parents[1]
SIMULATOR = ROOT / "tests" / "fixtures" / "station" / "simulated_engine.py"
SCHEMA = json.loads((ROOT / "docs" / "schemas" / "station-event.schema.json").read_text(encoding="utf-8"))
OK = {"checked", "already", "unsupported", "skipped"}


def validate_event(event: dict[str, Any]) -> None:
    """Valida o envelope e o ramo condicional do tipo (o validador do projeto nao trata allOf)."""
    base = {key: value for key, value in SCHEMA.items() if key != "allOf"}
    validate_instance(event, base)
    for branch in SCHEMA["allOf"]:
        expected = branch["if"]["properties"]["type"]["const"]
        if event["type"] == expected:
            validate_instance(event, branch["then"], f"$<{expected}>")


def run_engine(state_dir: Path, *arguments: str, scenario: str = "default", os_name: str = "windows",
               answers: dict[str, Any] | None = None) -> tuple[int, list[dict[str, Any]], str]:
    env = dict(os.environ)
    env.update({
        "HUBICG_STATION_SIM_STATE": str(state_dir / "state.json"),
        "HUBICG_STATION_SIM_SCENARIO": scenario,
        "HUBICG_STATION_SIM_OS": os_name,
        "HUBICG_STATION_SIM_CODE_WAIT": "0",
        "PYTHONIOENCODING": "utf-8",
    })
    args = list(arguments)
    if answers is not None:
        path = state_dir / "answers.json"
        path.write_text(json.dumps({"schema": "hubicg.station.answers/1", "answers": answers}), encoding="utf-8")
        args += ["--answers-file", str(path)]
    args += ["--log-file", str(state_dir / f"log-{len(list(state_dir.glob('log-*')))}.jsonl")]
    result = subprocess.run(
        [sys.executable, str(SIMULATOR), *args],
        capture_output=True, text=True, encoding="utf-8", env=env, check=False,
    )
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    return result.returncode, events, result.stderr


class SimulatedEngineContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def assert_valid_run(self, events: list[dict[str, Any]], exit_code: int) -> None:
        self.assertGreaterEqual(len(events), 2)
        for event in events:
            validate_event(event)
        self.assertEqual(events[0]["type"], "run_start")
        self.assertEqual(events[-1]["type"], "run_end")
        self.assertEqual([event["seq"] for event in events], list(range(1, len(events) + 1)))
        self.assertEqual({event["runId"] for event in events}, {events[0]["runId"]})
        self.assertEqual(events[-1]["data"]["exitCode"], exit_code)
        # Gramatica: todo evento de etapa fica entre step_start e step_end da mesma etapa.
        current = None
        for event in events[1:-1]:
            if event["type"] == "step_start":
                self.assertIsNone(current)
                current = event["step"]
            elif event["type"] == "step_end":
                self.assertEqual(event["step"], current)
                current = None
            else:
                self.assertEqual(event["step"], current, event)
        self.assertIsNone(current)

    def test_check_dry_run_and_contract_version(self) -> None:
        code, events, _ = run_engine(self.dir, "--check", "--json", "--non-interactive")
        self.assertEqual(code, 5)
        self.assert_valid_run(events, 5)
        self.assertEqual(events[0]["data"]["mode"], "check")
        code, events, _ = run_engine(self.dir, "-WhatIf", "-Json", "-NonInteractive")
        self.assertEqual(code, 5)
        self.assert_valid_run(events, 5)
        self.assertTrue(any(e["status"].startswith("would_") for e in events if e["type"] == "step_end"))
        result = subprocess.run([sys.executable, str(SIMULATOR), "--contract-version"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.stdout.strip(), "hubicg.station.event/1")

    def test_apply_cycle_answers_and_idempotence(self) -> None:
        code, events, _ = run_engine(self.dir, "--json", "--non-interactive")
        self.assertEqual(code, 3)
        self.assert_valid_run(events, 3)
        actions = [e["data"]["id"] for e in events if e["type"] == "action_required"]
        self.assertEqual(actions, ["git-identity", "gh-login", "claude-login", "desktop-login-confirm"])
        blocking = [e for e in events if e["type"] == "action_required" and e["data"]["blocking"]]
        self.assertEqual([e["data"]["kind"] for e in blocking], ["browser_code"])
        resolved = [e for e in events if e["type"] == "action_resolved"]
        self.assertEqual(resolved[0]["status"], "completed")
        # O codigo de dispositivo vai para stdout, nunca para o arquivo de log (contrato, secao 8).
        log = Path(events[0]["data"]["logFile"]).read_text(encoding="utf-8")
        self.assertEqual(blocking[0]["data"]["code"], "ABCD-1234")
        self.assertIn("ABCD-1234", blocking[0]["message"])
        self.assertNotIn("ABCD-1234", log)
        self.assertNotIn('"code"', log)

        code, events, _ = run_engine(self.dir, "--json", "--non-interactive", answers={
            "git.name": "Maria Silva", "git.email": "maria@exemplo.com.br", "desktop.loginConfirmed": True,
        })
        self.assertEqual(code, 0)
        self.assert_valid_run(events, 0)

        code, events, _ = run_engine(self.dir, "--json", "--non-interactive")
        self.assertEqual(code, 0)
        statuses = {e["step"]: e["status"] for e in events if e["type"] == "step_end"}
        self.assertTrue(set(statuses.values()) <= OK, statuses)

    def test_linux_marks_desktop_unsupported_and_asks_for_path(self) -> None:
        code, events, _ = run_engine(self.dir, "--json", "--non-interactive", os_name="linux")
        self.assertEqual(code, 3)
        self.assert_valid_run(events, 3)
        statuses = {e["step"]: e["status"] for e in events if e["type"] == "step_end"}
        self.assertEqual(statuses["claude-desktop"], "unsupported")
        self.assertEqual(statuses["claude-desktop-auth"], "unsupported")
        kinds = {e["data"]["id"]: e["data"]["kind"] for e in events if e["type"] == "action_required"}
        self.assertEqual(kinds["claude-path"], "confirm")

    def test_failure_blocks_dependents(self) -> None:
        code, events, _ = run_engine(self.dir, "--json", "--non-interactive", scenario="fail")
        self.assertEqual(code, 1)
        self.assert_valid_run(events, 1)
        ends = {e["step"]: e for e in events if e["type"] == "step_end"}
        self.assertEqual(ends["claude-cli"]["status"], "failed")
        self.assertEqual(ends["claude-cli-auth"]["status"], "blocked")
        self.assertEqual(ends["claude-cli-auth"]["data"]["blockedBy"], ["claude-cli"])

    def test_other_scenarios_stay_valid(self) -> None:
        for scenario, expected in (("tls", 3), ("repo-access", 3), ("terminal-login", 3),
                                   ("code-timeout", 3), ("invalid-email", 3)):
            with self.subTest(scenario=scenario):
                state = self.dir / scenario
                state.mkdir()
                code, events, _ = run_engine(state, "--json", "--non-interactive", scenario=scenario)
                self.assertEqual(code, expected)
                self.assert_valid_run(events, expected)

    def test_usage_errors_and_unsupported_system(self) -> None:
        code, events, stderr = run_engine(self.dir, "--json", "--opcao-inexistente")
        self.assertEqual((code, events), (2, []))
        self.assertIn("opção desconhecida", stderr)
        code, events, _ = run_engine(self.dir, "--json", "--only", "etapa-inexistente")
        self.assertEqual((code, events), (2, []))
        code, events, _ = run_engine(self.dir, "--json", scenario="unsupported-os")
        self.assertEqual((code, events), (4, []))

    def test_only_selection_skips_the_rest(self) -> None:
        code, events, _ = run_engine(self.dir, "--json", "--non-interactive", "--only", "git,gh")
        self.assertEqual(code, 0)
        statuses = {e["step"]: e["status"] for e in events if e["type"] == "step_end"}
        self.assertEqual(statuses["environment"], "checked")
        self.assertEqual(statuses["git"], "installed")
        self.assertEqual(statuses["repo"], "skipped")


if __name__ == "__main__":
    unittest.main()
