<#
.SYNOPSIS
  Núcleo da interface W1 do instalador da estação HubICG: a lógica sem tela.

.DESCRIPTION
  Lê os eventos do motor (contrato hubicg.station.event/1, docs/architecture/station-installer-engine.md),
  mantém o estado de uma execução, monta a linha de comando do motor, grava o arquivo de respostas e
  traduz status, códigos de saída e pedidos de ação para os textos de station-ui-texts.json.

  Nada aqui instala ou configura: isso é do motor. Este arquivo é carregado por dot-source pela tela
  (HubICG-Station-UI.ps1) e pelos testes, e precisa rodar no Windows PowerShell 5.1.
#>

Set-StrictMode -Version 2.0

$script:StationEventSchema = 'hubicg.station.event/1'
$script:StationAnswersSchema = 'hubicg.station.answers/1'
$script:StationEmailPattern = '^[^@\s]+@[^@\s]+\.[^@\s]+$'

function Get-StationProperty {
  # Lê uma propriedade de PSCustomObject ou hashtable sem quebrar no StrictMode quando ela não existe.
  param($Object, [string]$Name, $Default = $null)
  if ($null -eq $Object) { return $Default }
  if ($Object -is [System.Collections.IDictionary]) {
    if ($Object.Contains($Name)) { return $Object[$Name] }
    return $Default
  }
  $property = $Object.PSObject.Properties[$Name]
  if ($null -eq $property) { return $Default }
  return $property.Value
}

function Import-StationTexts {
  param([string]$Path = (Join-Path (Split-Path -Parent $PSScriptRoot) 'station-ui-texts.json'))
  $raw = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
  return ($raw | ConvertFrom-Json)
}

function Format-StationText {
  param([string]$Template, [object[]]$Values = @())
  if ($Values.Count -eq 0) { return $Template }
  return [string]::Format($Template, $Values)
}

function Get-StationStepLabel {
  param($Texts, [string]$Step)
  $label = Get-StationProperty $Texts.steps $Step
  if ($label) { return $label }
  return $Step
}

function Get-StationStatusInfo {
  # Grupo e rótulo de um status de step_end. Status desconhecido conta como falha (contrato, seção 9).
  param($Texts, [string]$Status)
  $known = Get-StationProperty $Texts.statuses $Status
  if ($known) {
    return [pscustomobject]@{ Status = $Status; Label = $known.label; Group = $known.group; Known = $true }
  }
  return [pscustomobject]@{
    Status = $Status
    Label  = (Format-StationText $Texts.unknownStatus @($Status))
    Group  = 'failed'
    Known  = $false
  }
}

function Get-StationExitMessage {
  param($Texts, [int]$Code)
  $message = Get-StationProperty $Texts.exitCodes ([string]$Code)
  if ($message) { return $message }
  return (Format-StationText $Texts.exitCodes.unknown @($Code))
}

function Get-StationActionGuide {
  # Título e explicação de "o que vai acontecer" para um pedido de ação; id desconhecido usa o kind.
  param($Texts, $Action)
  $id = [string](Get-StationProperty $Action 'id' '')
  $kind = [string](Get-StationProperty $Action 'kind' '')
  $byId = Get-StationProperty $Texts.actions $id
  $byKind = Get-StationProperty $Texts.kinds $kind
  $title = $null; $guide = $null
  if ($byId) { $title = $byId.title; $guide = $byId.guide }
  elseif ($byKind) { $title = $byKind.title; $guide = $byKind.guide }
  if (-not $title) { $title = $Texts.kinds.external.title; $guide = $Texts.kinds.external.guide }
  return [pscustomobject]@{ Id = $id; Kind = $kind; Title = $title; Guide = $guide }
}

function ConvertFrom-StationEventLine {
  # Devolve o evento, ou $null para linha vazia, JSON inválido ou outro schema.
  param([string]$Line)
  if ([string]::IsNullOrWhiteSpace($Line)) { return $null }
  try { $event = $Line | ConvertFrom-Json -ErrorAction Stop } catch { return $null }
  if ($null -eq $event -or $event -isnot [pscustomobject]) { return $null }
  if ((Get-StationProperty $event 'schema') -ne $script:StationEventSchema) { return $null }
  if (-not (Get-StationProperty $event 'type')) { return $null }
  if ($null -eq (Get-StationProperty $event 'data')) {
    $event | Add-Member -NotePropertyName data -NotePropertyValue ([pscustomobject]@{}) -Force
  }
  return $event
}

function New-StationRunState {
  return @{
    RunId       = $null
    Mode        = $null
    Os          = $null
    Steps       = New-Object System.Collections.ArrayList
    Status      = @{}
    Messages    = @{}
    StepData    = @{}
    Current     = $null
    Index       = 0
    Total       = 0
    Percent     = $null
    Actions     = New-Object System.Collections.ArrayList
    Blocking    = $null
    Resolved    = New-Object System.Collections.ArrayList
    Logs        = New-Object System.Collections.ArrayList
    Environment = $null
    RepoDir     = $null
    ConfigDir   = $null
    LogFile     = $null
    ExitCode    = $null
    Ended       = $false
    LastSeq     = 0
    Gaps        = 0
    Ignored     = 0
    Recovered   = New-Object System.Collections.ArrayList
  }
}

function Update-StationRunState {
  # Aplica um evento ao estado. Devolve o tipo do evento, para a tela decidir o que redesenhar.
  param([hashtable]$State, $Event)
  if ($null -eq $Event) { $State.Ignored++; return $null }
  $seq = [int](Get-StationProperty $Event 'seq' 0)
  if ($State.LastSeq -gt 0 -and $seq -gt ($State.LastSeq + 1)) { $State.Gaps += $seq - $State.LastSeq - 1 }
  if ($seq -gt $State.LastSeq) { $State.LastSeq = $seq }
  $type = [string]$Event.type
  $step = [string](Get-StationProperty $Event 'step' '')
  $status = [string](Get-StationProperty $Event 'status' '')
  $message = [string](Get-StationProperty $Event 'message' '')
  $data = $Event.data

  switch ($type) {
    'run_start' {
      $State.RunId = $Event.runId
      $State.Mode = Get-StationProperty $data 'mode'
      $State.Os = Get-StationProperty $data 'os'
      $State.RepoDir = Get-StationProperty $data 'repoDir'
      $State.ConfigDir = Get-StationProperty $data 'configDir'
      $State.LogFile = Get-StationProperty $data 'logFile'
      $State.Steps.Clear()
      foreach ($item in @(Get-StationProperty $data 'steps' @())) { [void]$State.Steps.Add([string]$item) }
      $State.Total = $State.Steps.Count
    }
    'step_start' {
      if ($State.Steps -notcontains $step) { [void]$State.Steps.Add($step) }
      $State.Current = $step
      $State.Index = [int](Get-StationProperty $data 'index' ($State.Steps.IndexOf($step) + 1))
      $total = [int](Get-StationProperty $data 'total' 0)
      if ($total -gt 0) { $State.Total = $total }
      $State.Percent = $null
    }
    'progress' {
      $State.Percent = Get-StationProperty $data 'percent'
      $State.Messages[$step] = $message
    }
    'log' {
      [void]$State.Logs.Add([pscustomobject]@{
          Level   = $status
          Step    = $step
          Message = $message
          Command = Get-StationProperty $data 'command'
          Output  = Get-StationProperty $data 'output'
        })
    }
    'action_required' {
      $action = [pscustomobject]@{
        Step                = $step
        Message             = $message
        Id                  = [string](Get-StationProperty $data 'id' '')
        Kind                = [string](Get-StationProperty $data 'kind' '')
        Blocking            = [bool](Get-StationProperty $data 'blocking' $false)
        Answers             = @(Get-StationProperty $data 'answers' @())
        Command             = Get-StationProperty $data 'command'
        Url                 = Get-StationProperty $data 'url'
        Code                = Get-StationProperty $data 'code'
        TimeoutSeconds      = Get-StationProperty $data 'timeoutSeconds'
        BrowserOpenedByTool = [bool](Get-StationProperty $data 'browserOpenedByTool' $false)
      }
      if ($action.Blocking) { $State.Blocking = $action } else { [void]$State.Actions.Add($action) }
    }
    'action_resolved' {
      [void]$State.Resolved.Add([pscustomobject]@{ Id = (Get-StationProperty $data 'id'); Status = $status; Message = $message })
      $State.Blocking = $null
    }
    'step_end' {
      if ($State.Steps -notcontains $step) { [void]$State.Steps.Add($step) }
      $State.Status[$step] = $status
      $State.Messages[$step] = $message
      $State.StepData[$step] = $data
      if ($step -eq 'environment') { $State.Environment = $data }
      $State.Percent = $null
      if ($State.Blocking -and $State.Blocking.Step -eq $step) { $State.Blocking = $null }
    }
    'run_end' {
      $finalSteps = Get-StationProperty $data 'steps'
      if ($finalSteps) {
        foreach ($property in $finalSteps.PSObject.Properties) {
          $finalStep = $property.Name
          $finalStatus = $property.Value
          if ($finalStatus -isnot [string]) { continue }
          if ($State.Steps -notcontains $finalStep) { [void]$State.Steps.Add($finalStep) }
          if ($State.Status[$finalStep] -ne $finalStatus) {
            $State.Status[$finalStep] = $finalStatus
            $State.Messages[$finalStep] = 'Status recuperado do resumo do motor; detalhes indisponíveis.'
            [void]$State.Recovered.Add($finalStep)
          }
        }
      }
      $State.ExitCode = [int](Get-StationProperty $data 'exitCode' 1)
      $State.Ended = $true
      $State.Current = $null
    }
    default { $State.Ignored++ }
  }
  return $type
}

function Complete-StationRunState {
  # Fecha o estado com o código de saída do processo. Sem run_end, a execução foi interrompida (130).
  param([hashtable]$State, [int]$ProcessExitCode)
  if (-not $State.Ended) {
    if ($ProcessExitCode -in 2, 4) { $State.ExitCode = $ProcessExitCode }
    else { $State.ExitCode = 130 }
    $State.Ended = $true
  }
  $State.Blocking = $null
  if ($State.ExitCode -eq 0) {
    $texts = Import-StationTexts
    foreach ($status in $State.Status.Values) {
      if (-not (Get-StationStatusInfo $texts $status).Known) { $State.ExitCode = 1; break }
    }
  }
  return $State.ExitCode
}

function Get-StationEventWarning {
  param($Texts, [hashtable]$State)
  if ($State.Gaps -gt 0 -or $State.Recovered.Count -gt 0) {
    return (Format-StationText $Texts.eventWarning @($State.Gaps, $State.Recovered.Count))
  }
  return ''
}

function Get-StationOverallPercent {
  param([hashtable]$State)
  if ($State.Total -le 0) { return 0 }
  $done = @($State.Status.Keys).Count
  $partial = 0
  if ($State.Current -and -not $State.Status.ContainsKey($State.Current) -and $null -ne $State.Percent) {
    $partial = [double]$State.Percent / 100
  }
  $value = [int][math]::Floor((($done + $partial) / $State.Total) * 100)
  return [math]::Max(0, [math]::Min(100, $value))
}

function Get-StationSummary {
  # Agrupa as etapas pelo grupo do status, na ordem do motor.
  param($Texts, [hashtable]$State)
  $groups = [ordered]@{ failed = @(); action = @(); pending = @(); done = @(); ok = @() }
  foreach ($step in $State.Steps) {
    if (-not $State.Status.ContainsKey($step)) { continue }
    $info = Get-StationStatusInfo $Texts $State.Status[$step]
    $groups[$info.Group] += [pscustomobject]@{
      Step    = $step
      Label   = Get-StationStepLabel $Texts $step
      Status  = $info.Label
      Message = $State.Messages[$step]
    }
  }
  return $groups
}

function New-StationSession {
  # Resultado acumulado das execuções encadeadas de uma mesma instalação (aplicação, respostas, nova aplicação).
  return @{ Status = @{}; Messages = @{} }
}

function Merge-StationSession {
  # Junta uma execução à sessão. O que foi feito numa execução anterior não vira "Já estava" na seguinte:
  # o resumo final precisa dizer o que esta instalação fez. Devolve um estado pronto para o resumo.
  param($Texts, [hashtable]$Session, [hashtable]$State)
  foreach ($step in $State.Steps) {
    if (-not $State.Status.ContainsKey($step)) { continue }
    $new = $State.Status[$step]
    if ($Session.Status.ContainsKey($step)) {
      $previous = Get-StationStatusInfo $Texts $Session.Status[$step]
      if ($previous.Group -eq 'done' -and $new -in 'already', 'skipped') { continue }
    }
    $Session.Status[$step] = $new
    $Session.Messages[$step] = $State.Messages[$step]
  }
  $merged = @{}
  foreach ($key in $State.Keys) { $merged[$key] = $State[$key] }
  $merged.Status = $Session.Status.Clone()
  $merged.Messages = $Session.Messages.Clone()
  return $merged
}

function Get-StationEnvironmentRows {
  # Linhas do relatório de ambiente: Item, Valor, Severidade (ok, info, warn, error) e Explicação.
  param($Texts, $Data)
  $t = $Texts.environment
  $rows = New-Object System.Collections.ArrayList
  $add = {
    param($item, $value, $severity, $explain)
    [void]$rows.Add([pscustomobject]@{ Item = $item; Value = $value; Severity = $severity; Explain = $explain })
  }
  if ($null -eq $Data) { return @() }

  $os = Get-StationProperty $t.osNames ([string](Get-StationProperty $Data 'os' '')) (Get-StationProperty $Data 'os')
  & $add $t.os ('{0} {1} ({2})' -f $os, (Get-StationProperty $Data 'osVersion' ''), (Get-StationProperty $Data 'arch' '')).Trim() 'ok' ''
  $shell = Get-StationProperty $Data 'shell'
  if ($shell) { & $add $t.shell ('{0} {1}' -f $shell, (Get-StationProperty $Data 'shellVersion' '')).Trim() 'ok' '' }

  $admin = Get-StationProperty $Data 'admin'
  if ($null -ne $admin) { & $add $t.admin $(if ($admin) { $t.yes } else { $t.no }) 'info' '' }

  $sudo = Get-StationProperty $Data 'sudo'
  if ($sudo) {
    $label = Get-StationProperty $t.sudoValues $sudo $sudo
    if ($sudo -eq 'absent') { & $add $t.sudo $label 'warn' $t.explain.sudoAbsent }
    else { & $add $t.sudo $label 'ok' '' }
  }

  $manager = Get-StationProperty $Data 'packageManager'
  if ($manager) { & $add $t.packageManager $manager 'ok' '' }
  else { & $add $t.packageManager $t.none 'warn' $t.explain.noPackageManager }

  $disk = Get-StationProperty $Data 'diskFreeGB'
  if ($null -eq $disk) { & $add $t.diskFreeGB $t.notMeasured 'info' '' }
  elseif ([double]$disk -lt 5) { & $add $t.diskFreeGB ('{0:N1} GB' -f [double]$disk) 'warn' $t.explain.lowDisk }
  else { & $add $t.diskFreeGB ('{0:N1} GB' -f [double]$disk) 'ok' '' }

  $proxy = Get-StationProperty $Data 'proxy'
  $proxyNames = @()
  if ($proxy) { $proxyNames = @($proxy.PSObject.Properties | ForEach-Object { '{0}={1}' -f $_.Name, $_.Value }) }
  if ($proxyNames.Count -gt 0) { & $add $t.proxy ($proxyNames -join '; ') 'info' $t.explain.proxy }
  else { & $add $t.proxy $t.none 'ok' '' }

  $tls = [string](Get-StationProperty $Data 'tls' '')
  if ($tls) {
    $severity = @{ direct = 'ok'; inspected = 'warn'; suspected = 'warn'; unreachable = 'error'; skipped = 'info' }[$tls]
    if (-not $severity) { $severity = 'warn' }
    & $add $t.tls (Get-StationProperty $t.verdicts $tls $tls) $severity (Get-StationProperty $t.explain.tls $tls '')
  }

  $network = Get-StationProperty $Data 'network'
  if ($network -and $network -isnot [string]) {
    foreach ($hostEntry in $network.PSObject.Properties) {
      $verdict = [string](Get-StationProperty $hostEntry.Value 'verdict' '')
      $severity = 'ok'
      if ($verdict -eq 'unreachable') { $severity = 'error' } elseif ($verdict -ne 'direct') { $severity = 'warn' }
      & $add ('{0} {1}' -f $t.network, $hostEntry.Name) (Get-StationProperty $t.verdicts $verdict $verdict) $severity (Get-StationProperty $t.explain.tls $verdict '')
    }
  }

  $tools = Get-StationProperty $Data 'tools'
  if ($tools) {
    foreach ($tool in $tools.PSObject.Properties) {
      if ($tool.Value) { & $add ('{0}: {1}' -f $t.tools, $tool.Name) $tool.Value 'ok' '' }
      else { & $add ('{0}: {1}' -f $t.tools, $tool.Name) $t.absentTool 'info' '' }
    }
  }
  return $rows.ToArray()
}

function Get-StationEngineArguments {
  # Opções do motor no estilo PowerShell (Windows). A interface sempre usa -Json e -NonInteractive.
  param(
    [ValidateSet('check', 'plan', 'apply')][string]$Mode = 'apply',
    [string[]]$Only = @(),
    [string]$RepoDir,
    [string]$AnswersFile
  )
  $arguments = New-Object System.Collections.ArrayList
  if ($Mode -eq 'check') { [void]$arguments.Add('-Check') }
  if ($Mode -eq 'plan') { [void]$arguments.Add('-WhatIf') }
  [void]$arguments.Add('-Json')
  [void]$arguments.Add('-NonInteractive')
  $selected = @($Only | Where-Object { $_ })
  if ($selected.Count -gt 0) { [void]$arguments.Add('-Only'); [void]$arguments.Add(($selected -join ',')) }
  if ($RepoDir) { [void]$arguments.Add('-RepoDir'); [void]$arguments.Add($RepoDir) }
  if ($AnswersFile) { [void]$arguments.Add('-AnswersFile'); [void]$arguments.Add($AnswersFile) }
  return , $arguments.ToArray()
}

function ConvertTo-StationArgument {
  # Cita um argumento pelas regras do CommandLineToArgvW (ProcessStartInfo.Arguments no .NET Framework).
  param([string]$Value)
  if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
  $builder = New-Object System.Text.StringBuilder
  [void]$builder.Append('"')
  $slashes = 0
  foreach ($char in $Value.ToCharArray()) {
    if ($char -eq '\') { $slashes++; continue }
    if ($char -eq '"') { [void]$builder.Append('\', 2 * $slashes + 1); [void]$builder.Append('"') }
    else { if ($slashes) { [void]$builder.Append('\', $slashes) }; [void]$builder.Append($char) }
    $slashes = 0
  }
  if ($slashes) { [void]$builder.Append('\', 2 * $slashes) }
  [void]$builder.Append('"')
  return $builder.ToString()
}

function Get-StationEngineInvocation {
  # Programa e argumentos para rodar o motor. .ps1 roda no Windows PowerShell; .py, no Python (motor simulado).
  param([string]$EnginePath, [string[]]$Arguments)
  $extension = [System.IO.Path]::GetExtension($EnginePath).ToLowerInvariant()
  switch ($extension) {
    '.ps1' {
      $program = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
      $prefix = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $EnginePath)
    }
    '.py' {
      $python = Get-Command python.exe, py.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
      if (-not $python) { throw 'O motor simulado precisa do Python, que não foi encontrado.' }
      $program = $python.Source
      $prefix = @($EnginePath)
    }
    default { $program = $EnginePath; $prefix = @() }
  }
  $all = @($prefix) + @($Arguments)
  return [pscustomobject]@{
    FileName  = $program
    Arguments = $all
    CommandLine = (($all | ForEach-Object { ConvertTo-StationArgument ([string]$_) }) -join ' ')
  }
}

function Test-StationAnswerValue {
  # Validação local, só para orientar a pessoa antes de rodar o motor; quem decide é o motor.
  param([string]$Type, $Value, [bool]$Required)
  if ($Type -eq 'boolean') { return ($Value -is [bool]) -or (-not $Required -and $null -eq $Value) }
  $text = [string]$Value
  if ([string]::IsNullOrWhiteSpace($text)) { return -not $Required }
  if ($Type -eq 'email') { return $text.Trim() -match $script:StationEmailPattern }
  return $true
}

function New-StationAnswersFile {
  # Grava o arquivo de respostas (UTF-8 sem BOM) num caminho novo e devolve o caminho.
  param([System.Collections.IDictionary]$Answers, [string]$Directory = [System.IO.Path]::GetTempPath())
  $clean = [ordered]@{}
  foreach ($key in $Answers.Keys) {
    $value = $Answers[$key]
    if ($value -is [string]) { $value = $value.Trim() }
    $clean[[string]$key] = $value
  }
  $document = [ordered]@{ schema = $script:StationAnswersSchema; answers = $clean }
  $json = ConvertTo-Json -InputObject $document -Depth 5
  $name = 'hubicg-station-answers-{0}.json' -f ([guid]::NewGuid().ToString('N'))
  $path = Join-Path $Directory $name
  [System.IO.File]::WriteAllText($path, $json, (New-Object System.Text.UTF8Encoding($false)))
  return $path
}

function Start-StationTerminal {
  param([string]$Command, [string]$Path = $env:Path)
  $info = New-Object System.Diagnostics.ProcessStartInfo
  $info.FileName = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
  $info.Arguments = '-NoExit -NoProfile -Command ' + (ConvertTo-StationArgument $Command)
  # ShellExecute cria um console independente, mesmo se o assistente tiver console oculto.
  $info.UseShellExecute = $true
  $info.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Normal
  $previousPath = $env:Path
  try {
    $env:Path = $Path
    return [System.Diagnostics.Process]::Start($info)
  }
  finally { $env:Path = $previousPath }
}

function New-StationCaptureDirectory {
  param([string]$Root)
  $directory = Join-Path ([System.IO.Path]::GetFullPath($Root)) ('execucao-' + [guid]::NewGuid().ToString('N'))
  [void](New-Item -ItemType Directory -Path $directory)
  return $directory
}

function Remove-StationRunAnswers {
  param([hashtable]$Run)
  if ($Run -and $Run.AnswersFile) {
    if (Test-Path -LiteralPath $Run.AnswersFile) { Remove-Item -LiteralPath $Run.AnswersFile -Force }
    $Run.AnswersFile = $null
  }
}

function Stop-StationEngineRun {
  param([hashtable]$Run)
  if (-not $Run) { return }
  $process = $Run.Process
  if ($process -and -not $process.HasExited) {
    & taskkill.exe /PID $process.Id /T /F 2>&1 | Out-Null
    if (-not $process.WaitForExit(5000)) { throw 'O motor não terminou após a interrupção.' }
  }
  Remove-StationRunAnswers $Run
}

function Get-StationDefaultSelection {
  # Preserve a seleção histórica; capacidades OpenAI exigem escolha explícita.
  param([hashtable]$CheckState)
  $optional = @('codex-cli', 'codex-cli-auth', 'chatgpt-desktop', 'chatgpt-desktop-auth')
  $selection = @()
  foreach ($step in $CheckState.Steps) {
    if ($step -eq 'environment' -or $optional -contains $step) { continue }
    if ($CheckState.Status.ContainsKey($step) -and $CheckState.Status[$step] -eq 'unsupported') { continue }
    $selection += $step
  }
  return $selection
}
