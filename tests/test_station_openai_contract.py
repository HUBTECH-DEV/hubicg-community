"""Isolated resolver/package probes: no workstation app or credentials touched."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'installers/station/hubicg-station.ps1'


class OpenAiCatalogTests(unittest.TestCase):
    def test_catalog_does_not_select_optional_steps(self):
        catalog = json.loads((ROOT / 'installers/station/ui/station-ui-texts.json').read_text(encoding='utf-8'))
        for step in ('codex-cli', 'codex-cli-auth', 'chatgpt-desktop', 'chatgpt-desktop-auth'):
            self.assertIn(step, catalog['steps'])
        self.assertIn('codex-login', catalog['actions'])
        self.assertIn('chatgpt-desktop-login-confirm', catalog['actions'])


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'PowerShell Windows probes')
class OpenAiWindowsProbeTests(unittest.TestCase):
    def test_paths_override_precedence_and_current_user_package_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = root / 'probe.ps1'
            harness.write_text(r'''
param([string]$Engine, [string]$Root)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$ast = [Management.Automation.Language.Parser]::ParseFile($Engine, [ref]$null, [ref]$null)
foreach ($name in @('Get-CodexBinDir', 'Find-Codex', 'Get-ChatGptDesktopProbe')) {
    $node = $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name}, $true)[0]
    Invoke-Expression $node.Extent.Text
}
function Assert($Value, $Expected, $Label) {
    if ($Value -ne $Expected) { throw "assertion failed: $Label" }
}
$env:LOCALAPPDATA = Join-Path $Root 'local data'
$env:CODEX_INSTALL_DIR = $null
$default = Join-Path $env:LOCALAPPDATA 'Programs\OpenAI\Codex\bin'
Assert (Get-CodexBinDir) $default 'documented default'
$env:CODEX_INSTALL_DIR = Join-Path $Root 'override with spaces'
Assert (Get-CodexBinDir) $env:CODEX_INSTALL_DIR 'explicit installer override'
$script:onPath = 'existing-on-path.cmd'
function Find-Tool { param($Name) Assert $Name 'codex' 'resolver only codex'; return $script:onPath }
Assert (Find-Codex) 'existing-on-path.cmd' 'existing PATH has priority'
$script:onPath = $null
Assert ([bool](Find-Codex)) $false 'absent override command'
New-Item -ItemType Directory -Path $env:CODEX_INSTALL_DIR -Force | Out-Null
$exe = Join-Path $env:CODEX_INSTALL_DIR 'codex.exe'
[IO.File]::WriteAllText($exe, 'inert test fixture, never executed')
Assert (Find-Codex) $exe 'documented command outside inherited PATH'
$Isolated = $false
$script:packageState = 'installed'
function Get-AppxPackage {
    param([string]$Name, [switch]$AllUsers, $ErrorAction)
    Assert $Name 'OpenAI.Codex' 'official current ChatGPT package identity'
    Assert ([bool]$AllUsers) $false 'current user only'
    if ($script:packageState -eq 'installed') { return [pscustomobject]@{Name=$Name} }
    if ($script:packageState -eq 'absent') { return $null }
    throw 'synthetic unavailable package query'
}
Assert (Get-ChatGptDesktopProbe).state 'installed' 'per-user registration'
$script:packageState = 'absent'
Assert (Get-ChatGptDesktopProbe).state 'absent' 'successful empty query proves absence'
$script:packageState = 'error'
Assert (Get-ChatGptDesktopProbe).state 'unknown' 'discovery error is inconclusive'
Write-Output 'isolated probes passed'
''', encoding='utf-8')
            result = subprocess.run(
                ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                 str(harness), '-Engine', str(ENGINE), '-Root', str(root)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('isolated probes passed', result.stdout)
