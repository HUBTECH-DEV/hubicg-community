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

    def test_linux_selector_preserves_defaults_and_explicit_selection(self):
        from tests.test_station_ui_linux import ui
        optional = ['codex-cli', 'codex-cli-auth', 'chatgpt-desktop', 'chatgpt-desktop-auth']
        steps = ['environment', 'git', 'claude-cli', 'claude-desktop', 'agents', *optional]
        for status in ('skipped', 'missing', 'already'):
            state = ui.RunState()
            state.steps = steps.copy()
            state.status = {step: status for step in steps}
            state.status['claude-desktop'] = 'unsupported'
            before = state.status.copy()
            self.assertEqual(ui.default_selection(state), ['git', 'claude-cli', 'agents'])
            self.assertEqual(state.steps, steps)
            self.assertEqual(state.status, before)
            args = ui.engine_arguments('apply', optional)
            self.assertEqual(args[args.index('--only') + 1], ','.join(optional))

    @unittest.skipUnless(shutil.which('node'), 'existing Node for pure macOS selector tests')
    def test_macos_selector_preserves_defaults_and_explicit_selection(self):
        script = r'''
const assert = require('assert');
const core = require(process.argv[1]);
const optional = ['codex-cli','codex-cli-auth','chatgpt-desktop','chatgpt-desktop-auth'];
const steps = ['environment','git','claude-cli','claude-desktop','agents'].concat(optional);
['skipped','missing','already'].forEach(function(status) {
    const state = core.state(); state.steps = steps.slice();
    steps.forEach(function(step) {state.status[step] = status;});
    state.status['claude-desktop'] = 'unsupported';
    const before = JSON.stringify(state);
    assert.deepStrictEqual(core.selected(state), ['git','claude-cli','agents']);
    assert.strictEqual(JSON.stringify(state), before);
    const args = core.args('apply', optional, '', '');
    assert.strictEqual(args[args.indexOf('--only') + 1], optional.join(','));
});
'''
        result = subprocess.run(['node', '-e', script, str(ROOT / 'installers/station/ui/macos/StationUi.Core.js')],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'PowerShell Windows probes')
class OpenAiWindowsProbeTests(unittest.TestCase):
    def test_windows_selector_preserves_defaults_and_explicit_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            harness = Path(temporary) / 'selector.ps1'
            harness.write_text(r'''
param([string]$Core)
$ErrorActionPreference = 'Stop'
$ast = [Management.Automation.Language.Parser]::ParseFile($Core, [ref]$null, [ref]$null)
foreach ($name in @('Get-StationDefaultSelection', 'Get-StationEngineArguments')) {
    $node = $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name}, $true)[0]
    Invoke-Expression $node.Extent.Text
}
$optional = @('codex-cli','codex-cli-auth','chatgpt-desktop','chatgpt-desktop-auth')
$steps = @('environment','git','claude-cli','claude-desktop','agents') + $optional
foreach ($status in @('skipped','missing','already')) {
    $state = @{Steps=$steps.Clone(); Status=@{}}
    foreach ($step in $steps) { $state.Status[$step] = $status }
    $state.Status['claude-desktop'] = 'unsupported'
    $before = $state | ConvertTo-Json -Compress
    if (((Get-StationDefaultSelection $state) -join ',') -ne 'git,claude-cli,agents') { throw 'default selection changed' }
    if (($state | ConvertTo-Json -Compress) -ne $before) { throw 'capabilities or statuses mutated' }
    $arguments = Get-StationEngineArguments -Mode apply -Only $optional
    $index = [array]::IndexOf($arguments, '-Only')
    if ($arguments[$index + 1] -ne ($optional -join ',')) { throw 'explicit selection lost' }
}
''', encoding='utf-8')
            result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                     '-File', str(harness), '-Core', str(ROOT / 'installers/station/ui/windows/StationUi.Core.ps1')],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_paths_override_precedence_and_current_user_package_identity(self):
        import ctypes

        with tempfile.TemporaryDirectory(prefix='HubICG path probe ') as temporary:
            root = Path(temporary)
            roots = [('absolute', str(root)), ('dot-component', str(root) + r'\.')]
            # CI TEMP may use an 8.3 alias. Query only our own temporary directory;
            # never change the volume's short-name policy or depend on its spelling.
            get_short = ctypes.WinDLL('kernel32', use_last_error=True).GetShortPathNameW
            get_short.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
            get_short.restype = ctypes.c_uint
            short = ctypes.create_unicode_buffer(32768)
            size = get_short(str(root), short, len(short))
            if 0 < size < len(short) and short.value != str(root):
                roots.append(('short-alias', short.value))
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
$overrideInput = $env:CODEX_INSTALL_DIR
New-Item -ItemType Directory -Path $overrideInput -Force | Out-Null
$resolvedDirectory = Get-CodexBinDir
Assert $env:CODEX_INSTALL_DIR $overrideInput 'installer override is not mutated'
$script:onPath = 'existing-on-path.cmd'
function Find-Tool { param($Name) Assert $Name 'codex' 'resolver only codex'; return $script:onPath }
Assert (Find-Codex) 'existing-on-path.cmd' 'existing PATH has priority'
$script:onPath = $null
Assert ([bool](Find-Codex)) $false 'absent override command'
$exe = Join-Path $env:CODEX_INSTALL_DIR 'codex.exe'
[IO.File]::WriteAllText($exe, 'inert test fixture, never executed')
$resolvedCommand = Find-Codex
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
[ordered]@{message='isolated probes passed'; directory=$resolvedDirectory; command=$resolvedCommand} | ConvertTo-Json -Compress
''', encoding='utf-8')
            expected_directory = root / 'override with spaces'
            expected_command = expected_directory / 'codex.exe'
            for label, root_spelling in roots:
                with self.subTest(path=label):
                    expected_command.unlink(missing_ok=True)
                    result = subprocess.run(
                        ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                         str(harness), '-Engine', str(ENGINE), '-Root', root_spelling],
                        capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    evidence = json.loads(result.stdout)
                    self.assertEqual(evidence['message'], 'isolated probes passed')
                    self.assertTrue(os.path.isabs(evidence['directory']))
                    # Compare actual filesystem identity, not a second call to
                    # the implementation's normalization API or raw path text.
                    self.assertTrue(os.path.samefile(expected_directory, evidence['directory']), evidence)
                    self.assertTrue(os.path.samefile(expected_command, evidence['command']), evidence)
                    self.assertEqual(Path(evidence['command']).read_text(), 'inert test fixture, never executed')
