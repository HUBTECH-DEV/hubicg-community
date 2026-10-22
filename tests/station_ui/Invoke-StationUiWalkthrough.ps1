<#
.SYNOPSIS
  Percorre a interface W1 de ponta a ponta com o motor simulado e salva as capturas de tela.

.DESCRIPTION
  Abre HubICG-Station-UI.ps1 com o motor simulado (tests\fixtures\station\simulated_engine.py) e conduz o
  assistente como uma pessoa faria: verificação, seleção, instalação com o código de dispositivo, pendências
  (identidade do Git, login do Claude Code no terminal, confirmação do Claude Desktop), resumo e a segunda
  passada idempotente. Cada passo vira um PNG em -CaptureDir.

  Conduz pela acessibilidade do Windows (MSAA), localizando cada controle pelo nome acessível: o mesmo nome
  que um leitor de tela anuncia. Abre janelas na sessão interativa, então não roda em CI sem desktop. A
  validação real continua sendo na VM (docs\runbooks\station-ui-vm-validation.md).

.PARAMETER Scenario
  Cenário do motor simulado: default, fail, tls, repo-access, terminal-login ou unsupported-os.
#>
[CmdletBinding()]
param(
  [string]$CaptureDir = (Join-Path ([System.IO.Path]::GetTempPath()) 'hubicg-station-ui-capturas'),
  [string]$Scenario = 'default',
  [int]$TimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'
Add-Type -ReferencedAssemblies Accessibility -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using Accessibility;

public static class StationUiDriver {
  delegate bool EnumProc(IntPtr hwnd, IntPtr lParam);
  [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr parent, EnumProc callback, IntPtr lParam);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hwnd);
  [DllImport("user32.dll")] static extern bool IsWindowEnabled(IntPtr hwnd);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern IntPtr SendMessage(IntPtr hwnd, uint msg, IntPtr wParam, string lParam);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr hwnd, System.Text.StringBuilder name, int size);
  [DllImport("oleacc.dll")] static extern int AccessibleObjectFromWindow(IntPtr hwnd, uint id, ref Guid iid, [MarshalAs(UnmanagedType.Interface)] out object result);

  static IAccessible Acc(IntPtr hwnd) {
    Guid iid = new Guid("618736E0-3C3D-11CF-810C-00AA00389B71");
    object result;
    if (AccessibleObjectFromWindow(hwnd, 0xFFFFFFFC, ref iid, out result) != 0) return null;
    return result as IAccessible;
  }

  public static string Name(IntPtr hwnd) {
    IAccessible acc = Acc(hwnd);
    if (acc == null) return null;
    try { return acc.get_accName(0); } catch { return null; }
  }

  // Primeiro controle visível com este nome acessível (o que o leitor de tela anuncia).
  public static IntPtr Find(IntPtr top, string name, bool enabledOnly, string classContains) {
    IntPtr found = IntPtr.Zero;
    EnumChildWindows(top, delegate (IntPtr hwnd, IntPtr l) {
      if (!IsWindowVisible(hwnd)) return true;
      if (enabledOnly && !IsWindowEnabled(hwnd)) return true;
      if (!string.IsNullOrEmpty(classContains)) {
        System.Text.StringBuilder cls = new System.Text.StringBuilder(256);
        GetClassName(hwnd, cls, cls.Capacity);
        if (cls.ToString().IndexOf(classContains, StringComparison.OrdinalIgnoreCase) < 0) return true;
      }
      if (Name(hwnd) == name) { found = hwnd; return false; }
      return true;
    }, IntPtr.Zero);
    return found;
  }

  public static void Press(IntPtr hwnd) { Acc(hwnd).accDoDefaultAction(0); }

  public static void SetText(IntPtr hwnd, string text) { SendMessage(hwnd, 0x000C, IntPtr.Zero, text); }

  public static bool IsChecked(IntPtr hwnd) { return (((int)Acc(hwnd).get_accState(0)) & 0x10) != 0; }
}
'@

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $root 'installers\station\ui\windows\StationUi.Core.ps1')
$ui = Join-Path $root 'installers\station\ui\windows\HubICG-Station-UI.ps1'
$simulator = Join-Path $root 'tests\fixtures\station\simulated_engine.py'
$work = Join-Path ([System.IO.Path]::GetTempPath()) ('hubicg-station-ui-walk-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
$CaptureDir = New-StationCaptureDirectory $CaptureDir

$env:HUBICG_STATION_SIM_STATE = Join-Path $work 'state.json'
$env:HUBICG_STATION_SIM_OS = 'windows'
$env:HUBICG_STATION_SIM_SCENARIO = $Scenario
$env:HUBICG_STATION_SIM_DELAY_MS = '120'
$env:HUBICG_STATION_SIM_CODE_WAIT = '4'
$env:HUBICG_STATION_SIM_BROWSER_OPENED = '1'

function Wait-Until {
  param([scriptblock]$Condition, [string]$What)
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    $value = & $Condition
    if ($value) { return $value }
    Start-Sleep -Milliseconds 250
  }
  throw "Tempo esgotado esperando: $What"
}

function Find-Control {
  param([string]$Name, [switch]$Enabled, [string]$Class = '')
  $script:Process.Refresh()
  $handle = [StationUiDriver]::Find($script:Process.MainWindowHandle, $Name, [bool]$Enabled, $Class)
  if ($handle -ne [IntPtr]::Zero) { return $handle }
  return $null
}

function Wait-Screen {
  param([string]$Title)
  [void](Wait-Until { Find-Control $Title } "tela '$Title'")
  Start-Sleep -Milliseconds 900
}

function Invoke-Control {
  param([string]$Name)
  $handle = Wait-Until { Find-Control $Name -Enabled -Class 'BUTTON' } "controle '$Name'"
  [StationUiDriver]::Press($handle)
  Start-Sleep -Milliseconds 500
}

function Set-Field {
  param([string]$Name, [string]$Value)
  $handle = Wait-Until { Find-Control $Name -Enabled -Class 'EDIT' } "campo '$Name'"
  [StationUiDriver]::SetText($handle, $Value)
}

function Set-Checked {
  param([string]$Name)
  $handle = Wait-Until { Find-Control $Name -Enabled -Class 'BUTTON' } "caixa '$Name'"
  if (-not [StationUiDriver]::IsChecked($handle)) { [StationUiDriver]::Press($handle) }
}

$arguments = '-NoProfile -ExecutionPolicy Bypass -STA -File "{0}" -EnginePath "{1}" -CaptureDir "{2}"' -f $ui, $simulator, $CaptureDir
# Este ensaio requer a janela visível para conduzir o assistente e capturar cada passo.
$script:Process = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -PassThru
try {
  [void](Wait-Until { $script:Process.Refresh(); $script:Process.MainWindowHandle -ne [IntPtr]::Zero } 'janela do assistente')
  Wait-Screen 'Vamos preparar esta estação para o HubICG'
  Invoke-Control 'Verificar o computador'
  if ($Scenario -eq 'unsupported-os') {
    Wait-Screen 'Não é possível continuar'
    Invoke-Control 'Fechar'
    return
  }
  Wait-Screen 'Resultado da verificação'
  Invoke-Control 'Avançar'
  Wait-Screen 'O que instalar'
  Set-Field 'Pasta do clone do repositório' (Join-Path $work 'github\hubicg-community')
  Invoke-Control 'Instalar'

  if ($Scenario -eq 'default') {
    Wait-Screen 'Falta pouco: algumas coisas dependem de você'
    Invoke-Control 'Verificar e continuar'
    [void](Wait-Until { Find-Control 'Há campos a corrigir: veja os itens marcados.' } 'aviso de validação')
    Set-Field 'Nome' 'Maria Silva'
    Set-Field 'E-mail' 'maria@exemplo.com.br'
    Set-Checked 'Já entrei no Claude Desktop'
    Invoke-Control 'Verificar e continuar'
    Wait-Screen 'Resumo'
    Invoke-Control 'Rodar de novo'
    Wait-Screen 'Instalando e configurando'
    Wait-Screen 'Resumo'
  }
  else {
    [void](Wait-Until {
        (Find-Control 'Resumo') -or (Find-Control 'Falta pouco: algumas coisas dependem de você')
      } 'fim da execução')
    Start-Sleep -Milliseconds 900
    if (Find-Control 'Falta pouco: algumas coisas dependem de você') {
      Invoke-Control 'Deixar para depois'
      Wait-Screen 'Resumo'
    }
  }
  Invoke-Control 'Concluir'
}
finally {
  Start-Sleep -Milliseconds 500
  if (-not $script:Process.HasExited) { Stop-Process -Id $script:Process.Id -Force }
  foreach ($name in 'STATE', 'OS', 'SCENARIO', 'DELAY_MS', 'CODE_WAIT', 'BROWSER_OPENED') {
    Remove-Item "env:HUBICG_STATION_SIM_$name" -ErrorAction SilentlyContinue
  }
  $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
  $workPath = [System.IO.Path]::GetFullPath($work)
  if ($workPath.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
      (Split-Path -Leaf $workPath) -like 'hubicg-station-ui-walk-*') {
    Remove-Item -LiteralPath $workPath -Recurse -Force -ErrorAction SilentlyContinue
  }
}
Get-ChildItem -LiteralPath $CaptureDir -Filter *.png | Select-Object -ExpandProperty Name
