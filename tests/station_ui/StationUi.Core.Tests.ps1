<#
.SYNOPSIS
  Testes do núcleo da interface W1 (StationUi.Core.ps1), sem Pester, para rodar no Windows PowerShell 5.1.

.DESCRIPTION
  Usa o motor simulado (tests/fixtures/station/simulated_engine.py) para o ciclo completo: verificação,
  aplicação com pendências, respostas por arquivo e a segunda passada idempotente.
  Sai com 0 quando tudo passa e com 1 na primeira falha. É chamado por tests/test_station_ui_windows.py.
#>
param([string]$Python = 'python')

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $root 'installers\station\ui\windows\StationUi.Core.ps1')
$simulator = Join-Path $root 'tests\fixtures\station\simulated_engine.py'
$texts = Import-StationTexts
$script:failures = 0
$script:count = 0

function Assert-True {
  param([bool]$Condition, [string]$Name)
  $script:count++
  if (-not $Condition) { $script:failures++; Write-Output "FALHA: $Name" }
}

function Invoke-Simulator {
  # Roda o motor simulado como a tela roda, e devolve o estado reconstruído pelos eventos.
  param([string[]]$Arguments, [hashtable]$Environment)
  foreach ($key in $Environment.Keys) { Set-Item -Path "env:$key" -Value $Environment[$key] }
  $invocation = Get-StationEngineInvocation -EnginePath $simulator -Arguments $Arguments
  $info = New-Object System.Diagnostics.ProcessStartInfo
  $info.FileName = $invocation.FileName
  $info.Arguments = $invocation.CommandLine
  $info.UseShellExecute = $false
  $info.RedirectStandardOutput = $true
  $info.RedirectStandardError = $true
  $info.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
  $info.CreateNoWindow = $true
  $process = [System.Diagnostics.Process]::Start($info)
  $state = New-StationRunState
  while ($null -ne ($line = $process.StandardOutput.ReadLine())) {
    [void](Update-StationRunState $state (ConvertFrom-StationEventLine $line))
  }
  [void]$process.StandardError.ReadToEnd()
  $process.WaitForExit()
  [void](Complete-StationRunState $state $process.ExitCode)
  return @{ State = $state; ExitCode = $process.ExitCode }
}

# --- funções puras ------------------------------------------------------------------------------

Assert-True ((ConvertFrom-StationEventLine '') -eq $null) 'linha vazia é ignorada'
Assert-True ((ConvertFrom-StationEventLine 'texto qualquer') -eq $null) 'texto que não é JSON é ignorado'
Assert-True ((ConvertFrom-StationEventLine '{"schema":"outro/1","type":"log"}') -eq $null) 'outro schema é ignorado'
$event = ConvertFrom-StationEventLine '{"schema":"hubicg.station.event/1","runId":"r","seq":1,"ts":"2026-10-22T00:00:00Z","type":"log","step":"git","status":"warn","message":"ã","data":{},"novo":1}'
Assert-True ($null -ne $event -and $event.message -eq 'ã') 'evento válido com campo desconhecido é aceito'

$info = Get-StationStatusInfo $texts 'already'
Assert-True ($info.Group -eq 'ok' -and $info.Label -eq 'Já estava') 'already é ok, "Já estava"'
$info = Get-StationStatusInfo $texts 'status_novo'
Assert-True ($info.Group -eq 'failed' -and -not $info.Known) 'status desconhecido conta como falha'
$unknownState = New-StationRunState
[void](Update-StationRunState $unknownState ([pscustomobject]@{ type='step_end'; step='agents'; status='future_status'; data=@{} }))
[void](Update-StationRunState $unknownState ([pscustomobject]@{ type='run_end'; data=@{ exitCode=0 } }))
Assert-True ((Complete-StationRunState $unknownState 0) -eq 1) 'status desconhecido impede sucesso'
Assert-True ((Get-StationExitMessage $texts $unknownState.ExitCode) -ne (Get-StationExitMessage $texts 0)) 'resumo desconhecido comunica falha'
foreach ($status in 'checked', 'already', 'installed', 'updated', 'configured', 'unsupported', 'skipped', 'missing',
  'would_install', 'would_configure', 'would_update', 'action_required', 'blocked', 'failed') {
  Assert-True ((Get-StationStatusInfo $texts $status).Known) "status do contrato tem texto: $status"
}
foreach ($code in 0, 1, 2, 3, 4, 5, 130) {
  Assert-True ((Get-StationExitMessage $texts $code) -notmatch '\{0\}') "código de saída tem texto: $code"
}
Assert-True ((Get-StationExitMessage $texts 77) -match '77') 'código desconhecido aparece na mensagem'

$guide = Get-StationActionGuide $texts ([pscustomobject]@{ id = 'pedido-novo'; kind = 'run_in_terminal' })
Assert-True ($guide.Title -eq $texts.kinds.run_in_terminal.title) 'pedido desconhecido usa o texto do kind'
$guide = Get-StationActionGuide $texts @{ id = 'gh-login'; kind = 'browser_code' }
Assert-True ($guide.Title -eq 'Login no GitHub') 'pedido conhecido usa o texto do id'

$lostState = New-StationRunState
foreach ($line in @(
    '{"schema":"hubicg.station.event/1","runId":"r","seq":1,"type":"run_start","data":{"steps":["git"]}}',
    '{"schema":"hubicg.station.event/1","runId":"r","seq":2,"type":"step_start","step":"git","data":{"index":1,"total":1}}',
    '{"schema":"hubicg.station.event/1","runId":"r","seq":4,"type":"run_end","data":{"exitCode":0,"steps":{"git":"installed"}}}'
  )) {
  [void](Update-StationRunState $lostState (ConvertFrom-StationEventLine $line))
}
Assert-True ($lostState.Gaps -eq 1) 'lacuna de seq detectada'
Assert-True ($lostState.Status['git'] -eq 'installed') 'step_end ausente recuperado de run_end'
Assert-True ($lostState.Recovered -contains 'git') 'etapa recuperada identificada'
Assert-True ((Get-StationSummary $texts $lostState).done.Count -eq 1) 'etapa recuperada aparece no resumo'
Assert-True ((Get-StationEventWarning $texts $lostState) -match 'Relatório incompleto') 'aviso de perda disponível para a tela'

Assert-True ((ConvertTo-StationArgument 'simples') -eq 'simples') 'argumento sem espaço não é citado'
Assert-True ((ConvertTo-StationArgument 'C:\Program Files\x') -eq '"C:\Program Files\x"') 'argumento com espaço é citado'
Assert-True ((ConvertTo-StationArgument 'C:\dir com espaço\') -eq '"C:\dir com espaço\\"') 'barra final é duplicada'
Assert-True ((ConvertTo-StationArgument 'a"b') -eq '"a\"b"') 'aspas são escapadas'
Assert-True ((ConvertTo-StationArgument '') -eq '""') 'argumento vazio vira ""'

$arguments = Get-StationEngineArguments -Mode check -Only @('git', 'gh') -RepoDir 'C:\x y'
Assert-True (($arguments -join '|') -eq '-Check|-Json|-NonInteractive|-Only|git,gh|-RepoDir|C:\x y') 'argumentos do modo verificação'
$arguments = Get-StationEngineArguments -Mode apply -AnswersFile 'C:\a.json'
Assert-True (($arguments -join '|') -eq '-Json|-NonInteractive|-AnswersFile|C:\a.json') 'argumentos do modo aplicação'
Assert-True ($arguments -notcontains '-WhatIf') 'aplicação não simula'

Assert-True (Test-StationAnswerValue 'email' 'maria@exemplo.com.br' $true) 'e-mail válido'
Assert-True (-not (Test-StationAnswerValue 'email' 'maria' $true)) 'e-mail inválido'
Assert-True (-not (Test-StationAnswerValue 'string' '  ' $true)) 'obrigatório vazio'
Assert-True (Test-StationAnswerValue 'boolean' $true $true) 'booleano'

$temp = Join-Path ([System.IO.Path]::GetTempPath()) ('station-ui-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp | Out-Null
$answersPath = New-StationAnswersFile -Answers ([ordered]@{ 'git.name' = ' Maria Silva '; 'desktop.loginConfirmed' = $true }) -Directory $temp
$bytes = [System.IO.File]::ReadAllBytes($answersPath)
Assert-True ($bytes[0] -ne 0xEF) 'arquivo de respostas sem BOM'
$answers = [System.IO.File]::ReadAllText($answersPath) | ConvertFrom-Json
Assert-True ($answers.schema -eq 'hubicg.station.answers/1') 'schema das respostas'
Assert-True ($answers.answers.'git.name' -eq 'Maria Silva') 'resposta sem espaços nas pontas'
Assert-True ($answers.answers.'desktop.loginConfirmed' -eq $true) 'resposta booleana'

# Cada ensaio preserva a pasta recebida, mesmo se a execução seguinte falhar.
$sentinel = Join-Path $temp 'sentinela.txt'
[System.IO.File]::WriteAllText($sentinel, 'preservar')
$captureFirst = New-StationCaptureDirectory $temp
$captureSecond = New-StationCaptureDirectory $temp
Assert-True ($captureFirst -ne $captureSecond) 'cada ensaio tem pasta exclusiva'
Assert-True ([System.IO.File]::ReadAllText($sentinel) -eq 'preservar') 'capturas preservam sentinela da pasta recebida'
Assert-True (Test-Path -LiteralPath $answersPath) 'capturas preservam outros arquivos existentes'

# Fechar o assistente durante o motor encerra o processo e apaga respostas, sem depender do Timer.
$invocation = Get-StationEngineInvocation -EnginePath $simulator -Arguments @()
$processInfo = New-Object System.Diagnostics.ProcessStartInfo
$processInfo.FileName = $invocation.FileName
$processInfo.Arguments = '-c "import time; time.sleep(30)"'
$processInfo.UseShellExecute = $false
$processInfo.CreateNoWindow = $true
$testProcess = [System.Diagnostics.Process]::Start($processInfo)
$closingRun = @{ Process = $testProcess; AnswersFile = $answersPath }
try {
  Stop-StationEngineRun $closingRun
  Assert-True $testProcess.HasExited 'fechamento encerra motor em execução'
  Assert-True (-not (Test-Path -LiteralPath $answersPath)) 'fechamento remove respostas antes de descartar Timer'
  Stop-StationEngineRun $closingRun
  Assert-True ($null -eq $closingRun.AnswersFile) 'limpeza repetida é segura'
}
finally {
  if (-not $testProcess.HasExited) { $testProcess.Kill(); $testProcess.WaitForExit() }
  $testProcess.Dispose()
}
$answersPath = New-StationAnswersFile -Answers @{ 'git.name' = 'Maria Silva' } -Directory $temp
Remove-StationRunAnswers @{ AnswersFile = $answersPath }
Assert-True (-not (Test-Path -LiteralPath $answersPath)) 'falha de inicialização também remove respostas'

# O terminal oficial recebe PATH novo e não altera o PATH do assistente.
$terminalOutput = Join-Path $temp 'terminal-path.txt'
$parentPath = $env:Path
$terminalCommand = "[System.IO.File]::WriteAllText('" + $terminalOutput.Replace("'", "''") + "', " + '$env:Path); exit'
$terminalProcess = Start-StationTerminal -Command $terminalCommand -Path 'C:\hubicg-test-path'
try {
  Assert-True ($terminalProcess.WaitForExit(10000)) 'terminal independente executa comando sem login real'
  Assert-True ([System.IO.File]::ReadAllText($terminalOutput) -eq 'C:\hubicg-test-path') 'terminal recebe PATH atualizado'
  Assert-True ($env:Path -eq $parentPath) 'PATH do assistente preservado'
}
finally {
  if (-not $terminalProcess.HasExited) { $terminalProcess.Kill(); $terminalProcess.WaitForExit() }
  $terminalProcess.Dispose()
}

# --- ciclo completo com o motor simulado ---------------------------------------------------------

$environment = @{
  HUBICG_STATION_SIM_STATE     = (Join-Path $temp 'state.json')
  HUBICG_STATION_SIM_OS        = 'windows'
  HUBICG_STATION_SIM_SCENARIO  = 'default'
  HUBICG_STATION_SIM_CODE_WAIT = '0'
}

$check = Invoke-Simulator (Get-StationEngineArguments -Mode check) $environment
Assert-True ($check.ExitCode -eq 5 -and $check.State.ExitCode -eq 5) 'verificação inicial: código 5'
Assert-True ($check.State.Mode -eq 'check') 'run_start informa o modo'
Assert-True ($check.State.Steps.Count -eq 11) 'run_start informa as etapas'
Assert-True ($check.State.Gaps -eq 0 -and $check.State.Ignored -eq 0) 'sem lacuna de seq nem evento ignorado'
$rows = Get-StationEnvironmentRows $texts $check.State.Environment
Assert-True ($rows.Count -ge 8) 'relatório de ambiente com itens'
Assert-True (@($rows | Where-Object { $_.Item -like '*git' -and $_.Value -eq $texts.environment.absentTool }).Count -eq 1) 'ferramenta ausente explicada'
$selection = Get-StationDefaultSelection $check.State
Assert-True ($selection.Count -eq 10 -and $selection -notcontains 'environment') 'seleção padrão: todas as etapas'

$first = Invoke-Simulator (Get-StationEngineArguments -Mode apply) $environment
Assert-True ($first.ExitCode -eq 3) 'primeira aplicação: pendências (3)'
Assert-True ($first.State.Resolved.Count -eq 1 -and $first.State.Resolved[0].Status -eq 'completed') 'browser_code resolvido'
$ids = @($first.State.Actions | ForEach-Object { $_.Id })
Assert-True (($ids -join ',') -eq 'git-identity,claude-login,desktop-login-confirm') "pedidos pendentes: $($ids -join ',')"
Assert-True ($null -eq $first.State.Blocking) 'nenhum pedido bloqueante sobra'
$summary = Get-StationSummary $texts $first.State
Assert-True ($summary.action.Count -eq 3 -and $summary.done.Count -ge 5) 'resumo agrupa pendências e instalações'
Assert-True ((Get-StationOverallPercent $first.State) -eq 100) 'progresso geral 100% no fim'

$answersPath = New-StationAnswersFile -Answers ([ordered]@{
    'git.name' = 'Maria Silva'; 'git.email' = 'maria@exemplo.com.br'; 'desktop.loginConfirmed' = $true
  }) -Directory $temp
$second = Invoke-Simulator (Get-StationEngineArguments -Mode apply -AnswersFile $answersPath) $environment
Assert-True ($second.ExitCode -eq 0) "aplicação com respostas: 0 (veio $($second.ExitCode))"
$session = New-StationSession
[void](Merge-StationSession $texts $session $first.State)
$merged = Merge-StationSession $texts $session $second.State
Assert-True ($merged.Status['git'] -eq 'installed') 'sessão: o que a 1ª execução instalou não vira "já estava"'
Assert-True ($merged.Status['git-identity'] -eq 'configured') 'sessão: a pendência resolvida aparece como configurada'
Assert-True ((Get-StationSummary $texts $merged).action.Count -eq 0) 'sessão: nenhuma pendência no resumo final'
$rows = Get-StationEnvironmentRows $texts $first.State.Environment
Assert-True (@($rows | Where-Object { $_.Value -eq 'Direta' }).Count -ge 1) 'veredito de rede traduzido'

$third = Invoke-Simulator (Get-StationEngineArguments -Mode apply) $environment
$notOk = @($third.State.Status.Values | Where-Object { $_ -notin 'already', 'checked', 'unsupported', 'skipped' })
Assert-True ($third.ExitCode -eq 0 -and $notOk.Count -eq 0) 'segunda passada idempotente: tudo "já estava"'
Assert-True ((Get-StationSummary $texts $third.State).ok.Count -eq 11) 'resumo da segunda passada: 11 etapas ok'

$environment.HUBICG_STATION_SIM_STATE = Join-Path $temp 'state-fail.json'
$environment.HUBICG_STATION_SIM_SCENARIO = 'fail'
$failed = Invoke-Simulator (Get-StationEngineArguments -Mode apply) $environment
Assert-True ($failed.ExitCode -eq 1) 'falha: código 1'
Assert-True ($failed.State.Status['claude-cli'] -eq 'failed' -and $failed.State.Status['claude-cli-auth'] -eq 'blocked') 'falha bloqueia a dependente'
Assert-True (@($failed.State.Logs | Where-Object { $_.Level -eq 'error' }).Count -ge 1) 'log de erro registrado'

$environment.HUBICG_STATION_SIM_SCENARIO = 'unsupported-os'
$unsupported = Invoke-Simulator (Get-StationEngineArguments -Mode check) $environment
Assert-True ($unsupported.State.ExitCode -eq 4) 'sistema sem suporte: código 4 sem run_end'

$interrupted = New-StationRunState
Assert-True ((Complete-StationRunState $interrupted 1) -eq 130) 'sem run_end: interrompido (130)'

$usage = Invoke-Simulator @('-Json', '-OpcaoQueNaoExiste') $environment
Assert-True ($usage.State.ExitCode -eq 2) 'opção desconhecida: código 2'

Remove-Item -LiteralPath $temp -Recurse -Force
foreach ($key in $environment.Keys) { Remove-Item -Path "env:$key" -ErrorAction SilentlyContinue }

Write-Output ("{0} verificações, {1} falha(s)" -f $script:count, $script:failures)
if ($script:failures -gt 0) { exit 1 }
exit 0
