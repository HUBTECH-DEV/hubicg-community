"""Interface W1 (WinForms) do instalador da estacao: arquivos, textos e o nucleo no Windows PowerShell 5.1."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "installers" / "station" / "ui"
TEXTS = json.loads((UI / "station-ui-texts.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "docs" / "schemas" / "station-event.schema.json").read_text(encoding="utf-8"))
STEPS = ("environment", "git", "git-identity", "gh", "gh-auth", "repo", "claude-cli", "claude-cli-auth",
         "claude-desktop", "claude-desktop-auth", "agents")
CATALOG = ("git-identity", "git-system-cert-store", "gh-login", "repo-access", "claude-login", "claude-path",
           "claude-auth-unverified",
           "desktop-login-confirm", "package-manager-missing", "privilege-required")
POWERSHELL_FILES = sorted(
    list(UI.rglob("*.ps1")) + list((ROOT / "tests" / "station_ui").glob("*.ps1"))
)


def step_end_statuses() -> list[str]:
    for branch in SCHEMA["allOf"]:
        if branch["if"]["properties"]["type"]["const"] == "step_end":
            return branch["then"]["properties"]["status"]["enum"]
    raise AssertionError("schema sem ramo de step_end")


class StationUiFilesTests(unittest.TestCase):
    def test_powershell_files_are_utf8_with_single_bom(self) -> None:
        """PowerShell 5.1 le .ps1 sem BOM como ANSI e quebra strings com acento longe do erro."""
        self.assertGreaterEqual(len(POWERSHELL_FILES), 4)
        for path in POWERSHELL_FILES:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                data = path.read_bytes()
                self.assertTrue(data.startswith(b"\xef\xbb\xbf"), "sem BOM")
                self.assertFalse(data[3:].startswith(b"\xef\xbb\xbf"), "BOM duplicado")
                data.decode("utf-8")

    def test_no_password_or_token_field_in_any_interface(self) -> None:
        """Nenhum campo de senha ou token em nenhuma interface (#83)."""
        for path in [*POWERSHELL_FILES, *UI.rglob("*.py"), *UI.rglob("*.sh")]:
            text = path.read_text(encoding="utf-8-sig")
            with self.subTest(path=path.name):
                for forbidden in ("UseSystemPasswordChar", "PasswordChar", "--password", "--hide-text",
                                  "getpass", "read -s"):
                    self.assertNotIn(forbidden, text)

    def test_texts_cover_the_contract(self) -> None:
        self.assertEqual(set(TEXTS["statuses"]), set(step_end_statuses()))
        self.assertTrue(set(STEPS) <= set(TEXTS["steps"]))
        self.assertTrue(set(CATALOG) <= set(TEXTS["actions"]))
        self.assertEqual(set(TEXTS["kinds"]), {"input", "confirm", "browser_code", "run_in_terminal", "external"})
        self.assertTrue({"0", "1", "2", "3", "4", "5", "130", "unknown"} <= set(TEXTS["exitCodes"]))
        for status in TEXTS["statuses"].values():
            self.assertIn(status["group"], TEXTS["groups"])

    def test_double_click_entry_point_targets_the_wizard(self) -> None:
        launcher = (UI / "windows" / "Instalar-HubICG-Estacao.cmd").read_text(encoding="ascii")
        self.assertIn('-File "%~dp0HubICG-Station-UI.ps1"', launcher)
        self.assertIn("-STA", launcher)


@unittest.skipUnless(sys.platform == "win32" and shutil.which("powershell"), "requer Windows PowerShell 5.1")
class StationUiWindowsCoreTests(unittest.TestCase):
    def test_core_against_simulated_engine(self) -> None:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(ROOT / "tests" / "station_ui" / "StationUi.Core.Tests.ps1")],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=300,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_wizard_script_parses(self) -> None:
        files = ",".join("'" + str(path).replace("'", "''") + "'" for path in POWERSHELL_FILES)
        script = (
            f"$errors = $null; foreach ($f in @({files})) {{ "
            "[void][System.Management.Automation.Language.Parser]::ParseFile($f, [ref]$null, [ref]$errors); "
            "if ($errors.Count) { $errors | ForEach-Object { Write-Output ($f + ': ' + $_.Message) }; exit 1 } }"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
