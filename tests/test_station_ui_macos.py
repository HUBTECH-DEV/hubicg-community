"""Testes locais M1 sem macOS, diálogos, autenticação ou instalação real."""
from __future__ import annotations

import shutil
import json
import os
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAC = ROOT / "installers/station/ui/macos"


@unittest.skipUnless(shutil.which("node"), "Node existente apenas para testar JavaScript localmente")
class MacCoreTests(unittest.TestCase):
    def test_contract_actions_and_summary(self) -> None:
        result = subprocess.run(["node", str(ROOT / "tests/station_ui/StationUi.Mac.Tests.js")],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_jxa_sources_parse_without_external_dependencies(self) -> None:
        for source in MAC.glob("*.js"):
            with self.subTest(source=source.name):
                result = subprocess.run(["node", "--check", str(source)], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class MacEntryTests(unittest.TestCase):
    def test_launcher_consumes_external_engine(self) -> None:
        launcher = (MAC / "Instalar-HubICG-Estacao.command").read_text(encoding="utf-8")
        self.assertIn('/usr/bin/osascript -l JavaScript', launcher)
        self.assertIn('"$@"', launcher)
        frontend = (MAC / "HubICG-Station-UI.js").read_text(encoding="utf-8")
        self.assertIn("--headless-check", frontend)
        self.assertIn("HUBICG_STATION_ENGINE", frontend)
        for forbidden in ("3structure.com.br", "system-prompt-ia3s", "brew install", "curl ", "with administrator privileges"):
            self.assertNotIn(forbidden, frontend)
        self.assertNotIn("hiddenAnswer", frontend)


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "adaptador de processos requer POSIX")
class MacProcessTests(unittest.TestCase):
    def test_native_check_fixture_obeys_event_schema(self) -> None:
        from test_station_simulator import validate_event
        result = subprocess.run(["bash", str(ROOT / "tests/fixtures/station/macos-check-engine.sh")],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 5)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        for event in events:
            validate_event(event)
        self.assertEqual(events[-1]["data"]["exitCode"], 5)

    def test_preserves_exit_code_and_closes_stdin(self) -> None:
        result = subprocess.run(["bash", str(MAC / "StationUi.Process.sh"), "bash", "-c",
                                 'read -r ignored && exit 9; printf "fixture\\n"; exit 3'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout, "fixture\n")

    def test_cancel_terminates_engine_group_ignoring_sigterm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "engine.sh"
            fixture.write_text('trap "" TERM\nsleep 60 &\nchild=$!\nprintf "%s\\n" "$child"\nwait "$child"\n', encoding="utf-8")
            process = subprocess.Popen(["bash", str(MAC / "StationUi.Process.sh"), "bash", str(fixture)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                child = int(process.stdout.readline().strip())
                process.send_signal(signal.SIGTERM)
                output, errors = process.communicate(timeout=8)
                self.assertEqual(process.returncode, 130, output + errors)
                child_stat = Path(f"/proc/{child}/stat")
                if child_stat.exists():
                    self.assertTrue(child_stat.read_text().split(") ", 1)[1].startswith("Z"))
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=8)


if __name__ == "__main__":
    unittest.main()
