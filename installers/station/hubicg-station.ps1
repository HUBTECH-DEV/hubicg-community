<#
.SYNOPSIS
  HubICG station installer engine for Windows (issue #80).

.DESCRIPTION
  Checks the environment, then installs and configures Git, GitHub CLI, the
  HUBTECH-DEV/hubicg-community clone, Claude Code CLI and Claude Desktop, and
  installs the HubICG agents rendered from the role library into the Claude
  configuration directory.

  The engine is idempotent: a second run changes nothing and reports "already"
  for every item. It never asks for, reads, prints or stores a token, password
  or cookie: logins go through each tool's own official flow.

  With -Json every event is one JSON object per line on stdout. The contract
  shared with the graphical interfaces (#83) is
  docs/architecture/station-installer-engine.md.

.EXAMPLE
  .\installers\station\hubicg-station.ps1 -Check
.EXAMPLE
  .\installers\station\hubicg-station.ps1 -WhatIf
.EXAMPLE
  .\installers\station\hubicg-station.ps1 -Json -NonInteractive -AnswersFile respostas.json
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Check,
    [switch]$Json,
    [switch]$NonInteractive,
    [string[]]$Only = @(),
    [string]$RepoDir = (Join-Path $HOME 'github\hubicg-community'),
    [string]$ConfigDir = $(if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME '.claude' }),
    [string]$AnswersFile = '',
    [string]$LogFile = '',
    [string]$AgentsSource = '',
    [string]$GitName = '',
    [string]$GitEmail = '',
    [switch]$ConfirmDesktopLogin,
    [switch]$UseWindowsCertStore,
    [switch]$SkipNetwork,
    [switch]$ContractVersion,
    [string]$Repository = 'HUBTECH-DEV/hubicg-community',
    # Unknown options land here so they can end with the contract's exit code 2.
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$UnknownArguments = @()
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$EngineVersion = '1.0.0'
$EventSchema = 'hubicg.station.event/1'
if ($UnknownArguments.Count -gt 0) {
    [Console]::Error.WriteLine('Uso incorreto: opcao desconhecida: ' + ($UnknownArguments -join ' '))
    exit 2
}
if ($ContractVersion) { [Console]::Out.WriteLine($EventSchema); exit 0 }

$Utf8 = New-Object System.Text.UTF8Encoding($false)
try { [Console]::OutputEncoding = $Utf8 } catch { }

$Mode = if ($Check) { 'check' } elseif ($WhatIfPreference) { 'plan' } else { 'apply' }
# The mode decides what is changed; -WhatIf must not leak into cmdlets.
$WhatIfPreference = $false
$Interactive = (-not $NonInteractive) -and [Environment]::UserInteractive -and (-not [Console]::IsInputRedirected)
$RepoUrl = "https://github.com/$Repository.git"
$StateFile = Join-Path $ConfigDir '.hubicg-station.json'
$DefaultAgentsSource = -not $AgentsSource
if ($DefaultAgentsSource) { $AgentsSource = Join-Path $RepoDir '.hubicg\exports\station-agents' }
$RunId = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ') + '-' + ([Guid]::NewGuid().ToString('N').Substring(0, 4))

$AllSteps = @(
    'environment', 'git', 'git-identity', 'gh', 'gh-auth', 'repo',
    'claude-cli', 'claude-cli-auth', 'claude-desktop', 'claude-desktop-auth', 'agents'
)
$Depends = @{
    'git-identity'        = @('git')
    'gh-auth'             = @('gh')
    'repo'                = @('git', 'gh-auth')
    'claude-cli-auth'     = @('claude-cli')
    'claude-desktop-auth' = @('claude-desktop')
    'agents'              = @('repo')
}
$KnownAnswers = @('git.name', 'git.email', 'git.useSystemCertStore', 'desktop.loginConfirmed', 'claude.addToPath')
$Results = [ordered]@{}
$Script:Seq = 0
$Script:Env = @{ tls = 'skipped'; arch = '' }

# --- Sanitizing and log -------------------------------------------------------

function Protect-Text([string]$Text) {
    if (-not $Text) { return $Text }
    $t = $Text -replace '://[^@/\s]+@', '://***@'
    $t = $t -replace '\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-ant-[A-Za-z0-9_\-]{10,})', '[redacted]'
    $t = $t -replace '(?i)(bearer\s+)[A-Za-z0-9._\-]+', '$1[redacted]'
    return $t
}

function Limit-Output([string]$Text) {
    $t = Protect-Text $Text
    if ($t -and $t.Length -gt 4096) { $t = $t.Substring($t.Length - 4096) }
    return $t
}

if (-not $LogFile) {
    $logDir = Join-Path $env:LOCALAPPDATA 'HubICG\station\logs'
    $LogFile = Join-Path $logDir "station-$RunId.jsonl"
} else {
    $logDir = Split-Path -Parent $LogFile
}
try {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    Get-ChildItem -LiteralPath $logDir -Filter 'station-*.jsonl' -File |
        Sort-Object LastWriteTime -Descending | Select-Object -Skip 19 |
        Remove-Item -Force -ErrorAction SilentlyContinue
} catch {
    $LogFile = ''
}

# --- Events -------------------------------------------------------------------

function Send-Event {
    param([string]$Type, [string]$Step = '', [string]$Status = '', [string]$Message = '', $Data = $null)
    $Script:Seq++
    $payload = $(if ($null -eq $Data) { @{} } else { $Data })
    $evt = [ordered]@{
        schema = $EventSchema; runId = $RunId; seq = $Script:Seq
        ts = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        type = $Type; step = $Step; status = $Status; message = (Protect-Text $Message); data = $payload
    }
    $line = $evt | ConvertTo-Json -Compress -Depth 8
    if ($LogFile) {
        $logged = $line
        if ($Type -eq 'action_required' -and $payload.Contains('code') -and $payload.code) {
            # The one-time device code goes to the interface, never to disk.
            $copy = [ordered]@{}
            foreach ($k in $evt.Keys) { $copy[$k] = $evt[$k] }
            $copy.message = $copy.message.Replace([string]$payload.code, '[codigo omitido]')
            $dataCopy = [ordered]@{}
            foreach ($k in $payload.Keys) { $dataCopy[$k] = $payload[$k] }
            $dataCopy.code = '[omitido]'
            $copy.data = $dataCopy
            $logged = $copy | ConvertTo-Json -Compress -Depth 8
        }
        try { [IO.File]::AppendAllText($LogFile, $logged + "`n", $Utf8) } catch { }
    }
    if ($Json) {
        [Console]::Out.WriteLine($line)
        return
    }
    switch ($Type) {
        'run_start' { Write-Host "HubICG station $EngineVersion - modo: $Mode" }
        'step_end' { Write-Host ('[{0}] {1}: {2}' -f $Step, $Status, $evt.message) }
        'action_required' {
            Write-Host ('[{0}] ACAO NECESSARIA: {1}' -f $Step, $evt.message) -ForegroundColor Yellow
            if ($payload.Contains('command') -and $payload.command) { Write-Host ('    comando: {0}' -f $payload.command) -ForegroundColor Yellow }
        }
        'log' {
            $color = if ($Status -eq 'warn') { 'Yellow' } elseif ($Status -eq 'error') { 'Red' } else { 'Gray' }
            Write-Host ('[{0}] {1}' -f $Step, $evt.message) -ForegroundColor $color
        }
        'run_end' { Write-Host $evt.message; if ($LogFile) { Write-Host "Log: $LogFile" } }
    }
}

function Write-Log([string]$Step, [string]$Level, [string]$Message, $Data = $null) {
    Send-Event -Type 'log' -Step $Step -Status $Level -Message $Message -Data $Data
}

function New-Answer([string]$Key, [string]$Type, [string]$Label) {
    return [ordered]@{ key = $Key; type = $Type; label = $Label; required = $true }
}

function Request-Action {
    param([string]$Step, [string]$Id, [string]$Kind, [string]$Message, [string]$Command = '', [string]$Url = '', $Answers = $null)
    $data = [ordered]@{ id = $Id; kind = $Kind; blocking = $false }
    if ($Answers) { $data.answers = @($Answers) }
    if ($Command) { $data.command = $Command }
    if ($Url) { $data.url = $Url }
    Send-Event -Type 'action_required' -Step $Step -Status 'action_required' -Message $Message -Data $data
}

function New-Result([string]$Status, [string]$Message, $Data = $null) {
    return @{ status = $Status; message = $Message; data = $(if ($null -eq $Data) { [ordered]@{} } else { $Data }) }
}

# --- Answers ------------------------------------------------------------------

$Answers = @{}
if ($GitName) { $Answers['git.name'] = $GitName }
if ($GitEmail) { $Answers['git.email'] = $GitEmail }
if ($ConfirmDesktopLogin) { $Answers['desktop.loginConfirmed'] = $true }
if ($UseWindowsCertStore) { $Answers['git.useSystemCertStore'] = $true }
$AnswerWarnings = @()
if ($AnswersFile) {
    try {
        $parsed = [IO.File]::ReadAllText($AnswersFile, $Utf8) | ConvertFrom-Json
        if ($parsed.schema -ne 'hubicg.station.answers/1' -or $parsed.answers -isnot [pscustomobject]) { throw 'schema/envelope nao suportado' }
        foreach ($p in $parsed.answers.PSObject.Properties) {
            if ($KnownAnswers -contains $p.Name) {
                if ($p.Name -in @('git.name', 'git.email')) {
                    if ($p.Value -isnot [string] -or $p.Value -match '[\x00-\x1f\x7f]') { throw 'resposta de identidade invalida' }
                } elseif ($p.Value -isnot [bool]) { throw 'resposta booleana invalida' }
                if (-not $Answers.ContainsKey($p.Name)) { $Answers[$p.Name] = $p.Value }
            } else {
                $AnswerWarnings += "Resposta desconhecida ignorada: $($p.Name)"
            }
        }
    } catch {
        [Console]::Error.WriteLine('Arquivo de respostas invalido: confira o JSON, schema e tipos das respostas.')
        exit 2
    }
}

function Get-Answer([string]$Key) {
    if ($Answers.ContainsKey($Key)) { return $Answers[$Key] }
    return $null
}

# --- Tools --------------------------------------------------------------------

function Find-Tool([string]$Name) {
    $cmd = Get-Command -Name $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { return $cmd.Source }
    return $null
}

function Invoke-Tool([string]$Name, [string[]]$Arguments) {
    $path = Find-Tool $Name
    if (-not $path) { return @{ code = 127; out = '' } }
    # PowerShell 5.1's native argument binder loses embedded quotes. Use the
    # same explicit argv encoding as the bounded probes (also for Git names).
    $process = [System.Diagnostics.Process]::Start((New-ToolStartInfo $path $Arguments))
    $process.StandardInput.Close()
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $result = @{ code = $process.ExitCode; out = ($stdout.Result + $stderr.Result).Trim() }
    $process.Dispose()
    return $result
}

function New-ToolStartInfo([string]$Path, [string[]]$Arguments) {
    # Process.Start without the shell runs native executables. A batch
    # launcher (claude.cmd from an npm install, for example) goes through
    # cmd.exe explicitly, with each argument quoted.
    $quoted = ($Arguments | ForEach-Object {
        # Windows CRT quoting: double backslashes preceding a quote or the
        # closing delimiter, preserving empty arguments as well.
        $escaped = [regex]::Replace($_, '(\\*)"', '$1$1\"')
        '"' + [regex]::Replace($escaped, '(\\+)$', '$1$1') + '"'
    }) -join ' '
    $info = New-Object System.Diagnostics.ProcessStartInfo
    if ($Path -match '\.(cmd|bat)$') {
        $info.FileName = $env:ComSpec
        $info.Arguments = '/d /s /c ""' + $Path + '" ' + $quoted + '"'
    } else {
        $info.FileName = $Path
        $info.Arguments = $quoted
    }
    $info.UseShellExecute = $false
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = $Utf8
    $info.StandardErrorEncoding = $Utf8
    $info.CreateNoWindow = $true
    return $info
}

function Invoke-Attached([string]$Name, [string[]]$Arguments) {
    # Interactive official flows need the console of the person at the keyboard.
    $path = Find-Tool $Name
    if (-not $path) { return 127 }
    & $path @Arguments
    return $LASTEXITCODE
}

function Get-ToolVersion([string]$Name) {
    if (-not (Find-Tool $Name)) { return $null }
    $r = Invoke-Tool $Name @('--version')
    if ($r.code -ne 0) { return $null }
    $match = [regex]::Match($r.out, '\d+(\.\d+)+')
    if ($match.Success) { return $match.Value }
    return ($r.out -split "`n")[0]
}

# Test seam: automated tests must never see or change this machine's real
# PATH, so with it set the user PATH lives in a process variable instead.
$Isolated = $env:HUBICG_STATION_TEST_ISOLATED -eq '1'

function Get-UserPath {
    if ($Isolated) { return [string]$env:HUBICG_STATION_TEST_USER_PATH }
    return [string]([Environment]::GetEnvironmentVariable('Path', 'User'))
}

function Set-UserPath([string]$Value) {
    if ($Isolated) { $env:HUBICG_STATION_TEST_USER_PATH = $Value; return }
    [Environment]::SetEnvironmentVariable('Path', $Value, 'User')
}

function Update-SessionPath {
    # A fresh install lands in the registry PATH; keep this process's entries first.
    if ($Isolated) { return }
    $current = @($env:Path -split ';' | Where-Object { $_ })
    $stored = @(
        [Environment]::GetEnvironmentVariable('Path', 'Machine'),
        (Get-UserPath)
    ) -join ';' -split ';' | Where-Object { $_ }
    $merged = New-Object System.Collections.Generic.List[string]
    foreach ($entry in @($current + $stored)) {
        if (-not ($merged -contains $entry)) { $merged.Add($entry) }
    }
    $env:Path = $merged -join ';'
}

function Get-WingetInstall([string]$Id) {
    return @('install', '--id', $Id, '--exact', '--source', 'winget', '--silent',
        '--accept-package-agreements', '--accept-source-agreements')
}

function Install-WithWinget([string]$Step, [string]$Id, [string]$Tool) {
    if (-not (Find-Tool 'winget')) {
        Request-Action -Step $Step -Id 'package-manager-missing' -Kind 'external' `
            -Message 'O winget nao foi encontrado. Instale o "App Installer" pela Microsoft Store e rode o instalador de novo.' `
            -Url 'https://apps.microsoft.com/detail/9NBLGGH4NNS1'
        return (New-Result 'action_required' 'winget ausente')
    }
    Send-Event -Type 'progress' -Step $Step -Message "Instalando $Id pelo winget"
    $r = Invoke-Tool 'winget' (Get-WingetInstall $Id)
    Update-SessionPath
    $version = Get-ToolVersion $Tool
    if (-not $version) {
        return (New-Result 'failed' "o winget nao concluiu a instalacao de $Id (codigo $($r.code))" ([ordered]@{ output = (Limit-Output $r.out) }))
    }
    return (New-Result 'installed' "$Tool $version instalado" ([ordered]@{ version = $version }))
}

function Read-YesNo([string]$Question) {
    if (-not $Interactive) { return $false }
    $answer = Read-Host "$Question [s/N]"
    return ($answer -match '^(s|sim|y|yes)$')
}

function Save-Download([string]$Step, [string]$Url, [string]$FileName) {
    # curl.exe uses Schannel, so it trusts the Windows certificate store, where a
    # corporate inspection CA is normally deployed. Verification stays on.
    $dir = Join-Path ([IO.Path]::GetTempPath()) ('hubicg-station-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    $target = Join-Path $dir $FileName
    $r = Invoke-Tool 'curl' @('-fsSL', '--retry', '2', '-o', $target, $Url)
    if ($r.code -ne 0 -or -not (Test-Path -LiteralPath $target)) {
        Write-Log $Step 'error' "Falha ao baixar $Url (codigo $($r.code)). Se a rede usa inspecao TLS, veja o aviso da etapa environment." ([ordered]@{ output = (Limit-Output $r.out) })
        Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
        return $null
    }
    return $target
}

# --- environment ----------------------------------------------------------------

$InspectionVendors = 'Netskope|Zscaler|Palo ?Alto|Fortinet|FortiGate|Umbrella|Forcepoint|Blue ?Coat|Symantec Web|McAfee Web|Skyhigh|Sophos|Check ?Point|Barracuda|Menlo|iboss|Cloudflare Gateway|Smoothwall|Kaspersky|ESET SSL'
$PublicCas = 'DigiCert|Sectigo|USERTrust|COMODO|GlobalSign|Let.s Encrypt|ISRG|Google Trust|GTS |Amazon|Microsoft|Entrust|GoDaddy|Starfield|Baltimore|IdenTrust|Certum|SSL\.com|QuoVadis|Buypass|Actalis|HARICA'

function Get-TlsProbe([string]$HostName) {
    if ($env:HUBICG_STATION_TEST_TLS_ISSUER) {
        return @{ reachable = $true; issuer = $env:HUBICG_STATION_TEST_TLS_ISSUER; root = ''; errors = 'None' }
    }
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($HostName, 443, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(8000)) { return @{ reachable = $false } }
        $client.EndConnect($async)
        $captured = @{ issuer = ''; root = ''; errors = '' }
        # The callback only observes the chain and returns the platform's own
        # verdict, so this probe never weakens certificate verification.
        $callback = [System.Net.Security.RemoteCertificateValidationCallback] {
            param($sender, $certificate, $chain, $errors)
            $captured.issuer = $certificate.Issuer
            if ($chain -and $chain.ChainElements.Count -gt 0) {
                $captured.root = $chain.ChainElements[$chain.ChainElements.Count - 1].Certificate.Subject
            }
            $captured.errors = "$errors"
            return ($errors -eq [System.Net.Security.SslPolicyErrors]::None)
        }
        $ssl = New-Object System.Net.Security.SslStream($client.GetStream(), $false, $callback)
        try { $ssl.AuthenticateAsClient($HostName) } catch { } finally { $ssl.Dispose() }
        return @{ reachable = $true; issuer = $captured.issuer; root = $captured.root; errors = $captured.errors }
    } catch {
        return @{ reachable = $false }
    } finally {
        $client.Close()
    }
}

function Get-TlsVerdict($Probe) {
    if (-not $Probe.reachable) { return 'unreachable' }
    if ("$($Probe.issuer) $($Probe.root)" -match $InspectionVendors) { return 'inspected' }
    if ($Probe.issuer -and ($Probe.issuer -notmatch $PublicCas)) { return 'suspected' }
    return 'direct'
}

function Step-Environment {
    $arch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    $free = $null
    try {
        $qualifier = (Split-Path -Qualifier ([IO.Path]::GetFullPath($RepoDir))).TrimEnd(':')
        $free = [math]::Round((Get-PSDrive -Name $qualifier).Free / 1GB, 1)
    } catch { }

    $proxy = [ordered]@{}
    foreach ($name in @('HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY')) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value) { $proxy[$name] = (Protect-Text $value) }
    }
    try {
        $system = [System.Net.WebRequest]::GetSystemWebProxy().GetProxy([Uri]'https://github.com')
        if ($system.Host -ne 'github.com') { $proxy['system'] = (Protect-Text $system.AbsoluteUri) }
    } catch { }

    $tools = [ordered]@{}
    foreach ($tool in @('winget', 'git', 'gh', 'claude', 'curl')) { $tools[$tool] = Get-ToolVersion $tool }
    $data = [ordered]@{
        os = 'windows'; osVersion = [Environment]::OSVersion.Version.ToString(); arch = $arch
        shell = 'powershell'; shellVersion = $PSVersionTable.PSVersion.ToString()
        admin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator); sudo = $null
        packageManager = $(if ($tools.winget) { 'winget' } else { $null })
        diskFreeGB = $free; proxy = $proxy; tools = $tools; network = 'skipped'; tls = 'skipped'
    }

    $warnings = @()
    if (-not $tools.winget) { $warnings += 'winget ausente: as instalacoes vao pedir o App Installer.' }
    if (-not $tools.curl) { $warnings += 'curl.exe ausente: o Claude Code CLI e o Claude Desktop nao poderao ser baixados.' }
    if ($null -ne $free -and $free -lt 2) { $warnings += "Pouco espaco livre no volume do clone: $free GB (recomendado: 2 GB)." }

    if (-not $SkipNetwork) {
        $network = [ordered]@{}
        $verdicts = @()
        foreach ($h in @('github.com', 'api.github.com', 'claude.ai', 'api.anthropic.com', 'downloads.claude.ai')) {
            $probe = Get-TlsProbe $h
            $verdict = Get-TlsVerdict $probe
            $verdicts += $verdict
            $network[$h] = [ordered]@{
                verdict = $verdict
                issuer = $(if ($probe.reachable) { $probe.issuer } else { $null })
                trusted = $(if ($probe.reachable) { $probe.errors -eq 'None' } else { $null })
            }
            if (-not $probe.reachable) { $warnings += "Sem conexao com ${h}:443." }
            elseif ($probe.errors -ne 'None') { $warnings += "O certificado apresentado por $h nao e confiavel nesta maquina ($($probe.errors))." }
        }
        $data.network = $network
        $data.tls = if ($verdicts -contains 'inspected') { 'inspected' }
            elseif ($verdicts -contains 'suspected') { 'suspected' }
            elseif (@($verdicts | Where-Object { $_ -ne 'unreachable' }).Count -eq 0) { 'unreachable' }
            else { 'direct' }
    }
    $Script:Env = $data

    if ($data.tls -in @('inspected', 'suspected')) {
        Write-Log 'environment' 'warn' (
            'A rede reassina o TLS com uma CA corporativa (inspecao TLS, como a do Netskope). A verificacao TLS NAO sera desligada. ' +
            'O curl.exe e o gh usam o repositorio de certificados do Windows e funcionam se a CA estiver instalada nele. ' +
            'O Git for Windows usa OpenSSL por padrao e precisa de http.sslBackend=schannel (a etapa git pede essa confirmacao). ' +
            'O Claude Code nativo tambem le o repositorio do sistema; so precisa de NODE_EXTRA_CA_CERTS (caminho do PEM da CA) se a CA nao estiver nele. ' +
            'pip e npm precisam da CA configurada (pip: truststore ou PIP_CERT; npm: cafile). Peca o PEM da CA ao time de seguranca.'
        ) ([ordered]@{ tls = $data.tls })
    }
    foreach ($w in $warnings) { Write-Log 'environment' 'warn' $w }
    foreach ($w in $AnswerWarnings) { Write-Log 'environment' 'warn' $w }
    return (New-Result 'checked' ("Windows $($data.osVersion) $arch, PowerShell $($data.shellVersion), TLS: $($data.tls)") $data)
}

# --- git ----------------------------------------------------------------------

function Step-Git {
    $version = Get-ToolVersion 'git'
    if ($version) {
        $result = New-Result 'already' "git $version ja estava instalado" ([ordered]@{ version = $version })
    } elseif ($Mode -eq 'check') {
        return (New-Result 'missing' 'git nao instalado')
    } elseif ($Mode -eq 'plan') {
        return (New-Result 'would_install' 'instalaria Git.Git pelo winget' ([ordered]@{ command = 'winget ' + ((Get-WingetInstall 'Git.Git') -join ' ') }))
    } else {
        $result = Install-WithWinget 'git' 'Git.Git' 'git'
        if ($result.status -ne 'installed') { return $result }
    }

    if ($Script:Env.tls -notin @('inspected', 'suspected')) { return $result }
    # Any scope counts: Git for Windows may set schannel in its system config,
    # and an explicit CA bundle that includes the corporate CA works as well.
    if ((Invoke-Tool 'git' @('config', '--get', 'http.sslBackend')).out -eq 'schannel') { return $result }
    if ((Invoke-Tool 'git' @('config', '--get', 'http.sslCAInfo')).out) { return $result }
    $command = 'git config --global http.sslBackend schannel'
    if ($Mode -eq 'check') { return (New-Result 'missing' 'com inspecao TLS, o git precisa de http.sslBackend=schannel') }
    if ($Mode -eq 'plan') { return (New-Result 'would_configure' 'configuraria http.sslBackend=schannel' ([ordered]@{ command = $command })) }
    $accepted = Get-Answer 'git.useSystemCertStore'
    if ($null -eq $accepted -and $Interactive) {
        $accepted = Read-YesNo 'A rede usa inspecao TLS. Configurar o Git para usar o repositorio de certificados do Windows (schannel)?'
    }
    if ($accepted -eq $true) {
        $w = Invoke-Tool 'git' @('config', '--global', 'http.sslBackend', 'schannel')
        if ($w.code -ne 0 -or (Invoke-Tool 'git' @('config', '--global', '--get', 'http.sslBackend')).out -ne 'schannel') {
            return (New-Result 'failed' 'nao foi possivel gravar http.sslBackend=schannel no git' ([ordered]@{ output = (Limit-Output $w.out) }))
        }
        $result.data.sslBackend = 'schannel'
        if ($result.status -eq 'already') { $result.status = 'configured' }
        $result.message += '; http.sslBackend=schannel configurado'
        return $result
    }
    Request-Action -Step 'git' -Id 'git-system-cert-store' -Kind 'confirm' -Command $command `
        -Message 'A rede usa inspecao TLS. Para o Git confiar na CA corporativa sem desligar a verificacao, ele precisa usar o repositorio de certificados do Windows (http.sslBackend=schannel). Autoriza?' `
        -Answers @((New-Answer 'git.useSystemCertStore' 'boolean' 'Usar o repositorio de certificados do Windows no Git'))
    return (New-Result 'action_required' 'confirmacao do http.sslBackend pendente')
}

function Step-GitIdentity {
    $name = (Invoke-Tool 'git' @('config', '--global', '--get', 'user.name')).out
    $email = (Invoke-Tool 'git' @('config', '--global', '--get', 'user.email')).out
    if ($name -and $email) { return (New-Result 'already' 'identidade do git ja configurada') }
    if ($Mode -eq 'check') { return (New-Result 'missing' 'user.name ou user.email vazio') }
    if ($Mode -eq 'plan') { return (New-Result 'would_configure' 'pediria user.name e user.email (so os vazios)') }

    $newName = $name
    $newEmail = $email
    if (-not $newName) { $newName = [string](Get-Answer 'git.name') }
    if (-not $newEmail) { $newEmail = [string](Get-Answer 'git.email') }
    if (-not $newName -and $Interactive) { $newName = Read-Host 'Nome para os commits (git user.name)' }
    if (-not $newEmail -and $Interactive) { $newEmail = Read-Host 'E-mail para os commits (git user.email)' }
    $problem = ''
    if (-not $newName -or -not $newEmail) { $problem = 'Informe o nome e o e-mail que vao assinar os commits.' }
    elseif ($newEmail -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$') { $problem = 'E-mail invalido. Informe de novo.' }
    if ($problem) {
        $asked = @()
        if (-not $name) { $asked += (New-Answer 'git.name' 'string' 'Nome') }
        if (-not $email) { $asked += (New-Answer 'git.email' 'email' 'E-mail') }
        Request-Action -Step 'git-identity' -Id 'git-identity' -Kind 'input' -Message $problem -Answers $asked
        return (New-Result 'action_required' 'identidade do git pendente')
    }
    foreach ($pair in @(@('user.name', $name, $newName), @('user.email', $email, $newEmail))) {
        if ($pair[1]) { continue }
        $w = Invoke-Tool 'git' @('config', '--global', $pair[0], $pair[2])
        if ($w.code -ne 0 -or (Invoke-Tool 'git' @('config', '--global', '--get', $pair[0])).out -ne $pair[2]) {
            return (New-Result 'failed' "nao foi possivel gravar $($pair[0]) no git")
        }
    }
    return (New-Result 'configured' 'identidade do git configurada')
}

# --- gh -----------------------------------------------------------------------

function Step-Gh {
    $version = Get-ToolVersion 'gh'
    if ($version) { return (New-Result 'already' "gh $version ja estava instalado" ([ordered]@{ version = $version })) }
    if ($Mode -eq 'check') { return (New-Result 'missing' 'gh nao instalado') }
    if ($Mode -eq 'plan') {
        return (New-Result 'would_install' 'instalaria GitHub.cli pelo winget' ([ordered]@{ command = 'winget ' + ((Get-WingetInstall 'GitHub.cli') -join ' ') }))
    }
    return (Install-WithWinget 'gh' 'GitHub.cli' 'gh')
}

function Test-GhAuth { return ((Invoke-Tool 'gh' @('auth', 'status', '--hostname', 'github.com')).code -eq 0) }

function Invoke-GhDeviceLogin {
    # Runs the official browser flow without a console. gh prints the one-time
    # code and the URL; both are relayed to the interface as a browser_code
    # action while the engine waits for gh to finish.
    param([int]$TimeoutSeconds = 900)
    $timeout = [Math]::Max(1, $TimeoutSeconds)
    $info = New-ToolStartInfo (Find-Tool 'gh') @('auth', 'login', '--hostname', 'github.com', '--git-protocol', 'https', '--web')
    $process = $null
    $clock = [Diagnostics.Stopwatch]::StartNew()
    try {
        $process = [System.Diagnostics.Process]::Start($info)
        $process.StandardInput.Close()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $code = ''; $url = 'https://github.com/login/device'; $announced = $false
        $pending = $process.StandardError.ReadLineAsync()
        while ($true) {
            if ($clock.Elapsed.TotalSeconds -ge $timeout) {
                try { if (-not $process.HasExited) { $process.Kill() } } catch { }
                Send-Event -Type 'action_resolved' -Step 'gh-auth' -Status 'timeout' -Message 'O codigo expirou sem login.' -Data ([ordered]@{ id = 'gh-login' })
                return $false
            }
            if ($null -ne $pending -and $pending.Wait(100)) {
                $line = $pending.Result
                if ($null -eq $line) { $pending = $null }
                else {
                    $m = [regex]::Match($line, 'one-time code:\s*([A-Z0-9]{4}-[A-Z0-9]{4})')
                    if ($m.Success) { $code = $m.Groups[1].Value }
                    $u = [regex]::Match($line, '(https://\S+/login/device\S*)')
                    if ($u.Success) { $url = $u.Groups[1].Value }
                    if ($code -and -not $announced -and ($u.Success -or $line -match 'Open this URL|browser')) {
                        $data = [ordered]@{ id = 'gh-login'; kind = 'browser_code'; blocking = $true; url = $url; code = $code; timeoutSeconds = $timeout; browserOpenedByTool = $false }
                        Send-Event -Type 'action_required' -Step 'gh-auth' -Status 'action_required' -Message "Abra $url e digite o codigo $code." -Data $data
                        $announced = $true
                    }
                    $pending = $process.StandardError.ReadLineAsync()
                }
            }
            # EOF on stderr does not mean the login process has exited.
            if ($process.HasExited -and $null -eq $pending) { break }
            if ($null -eq $pending) { Start-Sleep -Milliseconds 100 }
        }
        [void]$stdout.Wait(1000)
        $ok = ($process.ExitCode -eq 0) -and (Test-GhAuth)
        if ($announced) {
            Send-Event -Type 'action_resolved' -Step 'gh-auth' -Status $(if ($ok) { 'completed' } else { 'failed' }) -Message $(if ($ok) { 'Login no GitHub concluido.' } else { 'O login no GitHub nao foi concluido.' }) -Data ([ordered]@{ id = 'gh-login' })
        }
        return $ok
    } finally {
        $clock.Stop()
        if ($null -ne $process) {
            try { if (-not $process.HasExited) { $process.Kill() } } catch { }
            $process.Dispose()
        }
    }
}

function Step-GhAuth {
    $changed = @()
    if (-not (Test-GhAuth)) {
        if ($Mode -eq 'check') { return (New-Result 'missing' 'gh sem sessao valida em github.com') }
        if ($Mode -eq 'plan') { return (New-Result 'would_configure' 'conduziria o login oficial do gh pelo navegador e o gh auth setup-git') }
        if ($Interactive) {
            Write-Log 'gh-auth' 'info' 'Abrindo o login oficial do gh. Siga as instrucoes; o instalador nao ve o token.'
            Invoke-Attached 'gh' @('auth', 'login', '--hostname', 'github.com', '--git-protocol', 'https', '--web') | Out-Null
            $ok = Test-GhAuth
        } else {
            $ok = Invoke-GhDeviceLogin
        }
        if (-not $ok) { return (New-Result 'failed' 'o login do gh nao foi concluido; rode o instalador de novo para recomecar') }
        $changed += 'login'
    }

    if (Find-Tool 'git') {
        $helpers = (Invoke-Tool 'git' @('config', '--global', '--get-all', 'credential.https://github.com.helper')).out
        if ($helpers -notmatch 'auth git-credential') {
            if ($Mode -eq 'check') { return (New-Result 'missing' 'o git ainda nao usa a credencial do gh (gh auth setup-git)') }
            if ($Mode -eq 'plan') { return (New-Result 'would_configure' 'rodaria gh auth setup-git' ([ordered]@{ command = 'gh auth setup-git --hostname github.com' })) }
            $r = Invoke-Tool 'gh' @('auth', 'setup-git', '--hostname', 'github.com')
            if ($r.code -ne 0) { return (New-Result 'failed' 'gh auth setup-git falhou' ([ordered]@{ output = (Limit-Output $r.out) })) }
            $changed += 'setup-git'
        }
    }

    if ((Invoke-Tool 'gh' @('repo', 'view', $Repository, '--json', 'name')).code -ne 0) {
        if ($Mode -ne 'apply') { return (New-Result 'missing' "sem acesso a $Repository") }
        Request-Action -Step 'gh-auth' -Id 'repo-access' -Kind 'external' -Url "https://github.com/$Repository" `
            -Message "A sua conta do GitHub nao tem acesso a $Repository. Peca a um owner da organizacao HUBTECH-DEV que adicione a sua conta a um time com leitura no repositorio; depois, rode o instalador de novo."
        return (New-Result 'action_required' "sem acesso a $Repository")
    }
    if ($changed.Count -gt 0) { return (New-Result 'configured' ('gh: ' + ($changed -join ', ') + "; acesso a $Repository confirmado")) }
    return (New-Result 'already' "sessao do gh valida e acesso a $Repository confirmado")
}

# --- repo ---------------------------------------------------------------------

function Test-SameRepository([string]$Url) {
    $normalized = $Url.Trim().ToLowerInvariant() -replace '\.git$', '' -replace '^git@github\.com:', 'https://github.com/'
    return ($normalized -eq ('https://github.com/' + $Repository.ToLowerInvariant()))
}

function Step-Repo {
    if (-not (Test-Path -LiteralPath $RepoDir)) {
        if ($Mode -eq 'check') { return (New-Result 'missing' "clone ausente em $RepoDir") }
        if ($Mode -eq 'plan') { return (New-Result 'would_install' "clonaria $Repository em $RepoDir" ([ordered]@{ command = "git clone $RepoUrl `"$RepoDir`"" })) }
        $parent = Split-Path -Parent $RepoDir
        if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        Send-Event -Type 'progress' -Step 'repo' -Message "Clonando $Repository"
        $r = Invoke-Tool 'git' @('clone', $RepoUrl, $RepoDir)
        if ($r.code -ne 0) { return (New-Result 'failed' 'git clone falhou' ([ordered]@{ output = (Limit-Output $r.out) })) }
        return (New-Result 'installed' "clonado em $RepoDir" ([ordered]@{ path = $RepoDir }))
    }
    if (-not (Test-Path -LiteralPath (Join-Path $RepoDir '.git'))) {
        return (New-Result 'failed' "$RepoDir existe e nao e um clone git; nada foi alterado")
    }
    $origin = (Invoke-Tool 'git' @('-C', $RepoDir, 'remote', 'get-url', 'origin')).out
    if (-not (Test-SameRepository $origin)) {
        return (New-Result 'failed' "$RepoDir aponta para outro remoto ($(Protect-Text $origin)); nada foi alterado")
    }
    if ($Mode -eq 'check') { return (New-Result 'already' "clone presente em $RepoDir" ([ordered]@{ path = $RepoDir })) }
    if ($Mode -eq 'plan') { return (New-Result 'would_update' "faria fetch e pull --ff-only em $RepoDir" ([ordered]@{ path = $RepoDir; command = 'git pull --ff-only' })) }
    if ((Invoke-Tool 'git' @('-C', $RepoDir, 'status', '--porcelain')).out) {
        Write-Log 'repo' 'warn' 'O clone tem alteracoes locais. O pull nao foi feito, para nao descartar nada.'
        return (New-Result 'already' 'clone presente com alteracoes locais preservadas; atualizacao pulada' ([ordered]@{ path = $RepoDir; dirty = $true }))
    }
    $before = (Invoke-Tool 'git' @('-C', $RepoDir, 'rev-parse', 'HEAD')).out
    $fetch = Invoke-Tool 'git' @('-C', $RepoDir, 'fetch', '--prune', 'origin')
    if ($fetch.code -ne 0) { return (New-Result 'failed' 'git fetch falhou' ([ordered]@{ output = (Limit-Output $fetch.out) })) }
    $pull = Invoke-Tool 'git' @('-C', $RepoDir, 'pull', '--ff-only')
    if ($pull.code -ne 0) {
        Write-Log 'repo' 'warn' 'O pull --ff-only nao foi possivel (branch divergente ou sem upstream). Nada foi descartado; resolva manualmente.' ([ordered]@{ output = (Limit-Output $pull.out) })
        return (New-Result 'already' 'clone presente; avanco rapido impossivel, mantido como estava' ([ordered]@{ path = $RepoDir }))
    }
    $after = (Invoke-Tool 'git' @('-C', $RepoDir, 'rev-parse', 'HEAD')).out
    if ($before -eq $after) { return (New-Result 'already' "clone ja estava atualizado em $RepoDir" ([ordered]@{ path = $RepoDir; head = $after })) }
    return (New-Result 'updated' "clone atualizado em $RepoDir" ([ordered]@{ path = $RepoDir; head = $after }))
}

# --- claude-cli ---------------------------------------------------------------

# Official native installer: https://code.claude.com/docs/en/setup
$ClaudeInstallUrl = 'https://claude.ai/install.ps1'
$ClaudeBinDir = Join-Path $HOME '.local\bin'

function Test-UserPathHas([string]$Dir) {
    foreach ($entry in @((Get-UserPath) -split ';')) {
        if ($entry -and ($entry.TrimEnd('\') -ieq $Dir.TrimEnd('\'))) { return $true }
    }
    return $false
}

function Step-ClaudeCli {
    $version = Get-ToolVersion 'claude'
    $status = 'already'
    if (-not $version) {
        if ($Mode -eq 'check') { return (New-Result 'missing' 'Claude Code CLI nao instalado') }
        if ($Mode -eq 'plan') { return (New-Result 'would_install' "baixaria e rodaria o instalador oficial ($ClaudeInstallUrl)" ([ordered]@{ command = "irm $ClaudeInstallUrl | iex" })) }
        Send-Event -Type 'progress' -Step 'claude-cli' -Message 'Baixando o instalador oficial do Claude Code'
        $script = Save-Download 'claude-cli' $ClaudeInstallUrl 'install.ps1'
        if (-not $script) { return (New-Result 'failed' 'o download do instalador do Claude Code falhou') }
        try {
            $shell = Join-Path $PSHOME 'powershell.exe'
            $output = & $shell -NoProfile -ExecutionPolicy Bypass -File $script 2>&1 | ForEach-Object { "$_" }
        } finally {
            Remove-Item -LiteralPath (Split-Path -Parent $script) -Recurse -Force -ErrorAction SilentlyContinue
        }
        if ((Test-Path -LiteralPath $ClaudeBinDir) -and -not (($env:Path -split ';') -contains $ClaudeBinDir)) { $env:Path = "$ClaudeBinDir;$env:Path" }
        Update-SessionPath
        $version = Get-ToolVersion 'claude'
        if (-not $version) {
            return (New-Result 'failed' 'o instalador oficial terminou, mas o comando claude nao foi encontrado' ([ordered]@{ output = (Limit-Output ($output | Out-String)) }))
        }
        $status = 'installed'
    }

    $path = Find-Tool 'claude'
    $data = [ordered]@{ version = $version; path = $path; configDir = $ConfigDir }
    $message = "Claude Code $version" + $(if ($status -eq 'already') { ' ja estava instalado' } else { ' instalado' })
    if (((Split-Path -Parent $path).TrimEnd('\') -ieq $ClaudeBinDir.TrimEnd('\')) -and -not (Test-UserPathHas $ClaudeBinDir)) {
        if ($Mode -eq 'check') { return (New-Result 'missing' "$ClaudeBinDir nao esta no PATH do usuario" $data) }
        if ($Mode -eq 'plan') { return (New-Result 'would_configure' "incluiria $ClaudeBinDir no PATH do usuario" $data) }
        $user = Get-UserPath
        $joined = if ($user) { $user.TrimEnd(';') + ';' + $ClaudeBinDir } else { $ClaudeBinDir }
        Set-UserPath $joined
        $message += "; $ClaudeBinDir incluido no PATH do usuario"
        if ($status -eq 'already') { $status = 'configured' }
    }
    if ($env:CLAUDE_CONFIG_DIR) { $message += "; CLAUDE_CONFIG_DIR respeitado ($($env:CLAUDE_CONFIG_DIR))" }
    if ($Script:Env.tls -in @('inspected', 'suspected')) {
        $data.nodeExtraCaCerts = [bool]($env:NODE_EXTRA_CA_CERTS -and (Test-Path -LiteralPath $env:NODE_EXTRA_CA_CERTS))
        if (-not $data.nodeExtraCaCerts) {
            Write-Log 'claude-cli' 'warn' 'Inspecao TLS detectada. O Claude Code nativo confia no repositorio de certificados do Windows; se a CA corporativa nao estiver nele, defina NODE_EXTRA_CA_CERTS com o caminho do PEM da CA. Nunca desligue a verificacao TLS.'
        }
    }
    return (New-Result $status $message $data)
}

function Invoke-ToolBounded([string]$Name, [string[]]$Arguments, [int]$Seconds) {
    # For read-only probes that must never wait on the console: stdin is
    # closed and the process is stopped after the time limit.
    $path = Find-Tool $Name
    if (-not $path) { return @{ code = 127; out = ''; timedOut = $false } }
    $info = New-ToolStartInfo $path $Arguments
    $process = [System.Diagnostics.Process]::Start($info)
    $process.StandardInput.Close()
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit($Seconds * 1000)) {
        try { $process.Kill() } catch { }
        return @{ code = -1; out = ''; timedOut = $true }
    }
    $process.WaitForExit()
    return @{ code = $process.ExitCode; out = ($stdout.Result + $stderr.Result).Trim(); timedOut = $false }
}

function Get-ClaudeAuth {
    # state: logged_in, logged_out or unknown. Only a JSON answer counts as
    # "logged out": an old CLI without "auth status", a timeout or an error
    # must never be mistaken for a missing login and open the login flow.
    $r = Invoke-ToolBounded 'claude' @('auth', 'status') 30
    $info = @{ state = 'unknown'; authMethod = $null; configDirectory = $null; detail = '' }
    if ($r.timedOut) { $info.detail = 'claude auth status nao respondeu em 30 s'; return $info }
    try {
        $parsed = $r.out | ConvertFrom-Json
        if (($parsed.PSObject.Properties.Name -contains 'loggedIn') -and ($parsed.loggedIn -is [bool]) -and
            (($r.code -eq 0) -or ($parsed.loggedIn -eq $false))) {
            $info.state = $(if ($parsed.loggedIn) { 'logged_in' } else { 'logged_out' })
            # Only non-identifying fields leave this function: no e-mail, no org.
            $info.authMethod = $parsed.authMethod
            if ($parsed.PSObject.Properties.Name -contains 'configDirectory') { $info.configDirectory = $parsed.configDirectory }
            return $info
        }
    } catch { }
    $info.detail = "claude auth status respondeu sem o JSON esperado (codigo $($r.code))"
    return $info
}

function Step-ClaudeCliAuth {
    $auth = Get-ClaudeAuth
    $status = 'already'
    if ($auth.state -eq 'unknown') {
        if ($Mode -eq 'check') { return (New-Result 'missing' "sessao do Claude Code nao verificada: $($auth.detail)") }
        if ($Mode -eq 'plan') { return (New-Result 'would_configure' "conferiria a sessao do Claude Code ($($auth.detail))") }
        Request-Action -Step 'claude-cli-auth' -Id 'claude-auth-unverified' -Kind 'run_in_terminal' -Command 'claude auth status' `
            -Message "Nao foi possivel confirmar a sessao do Claude Code ($($auth.detail)). Num terminal, rode ""claude auth status""; se o comando nao existir, atualize com ""claude update"". Se nao houver login, rode ""claude auth login"". Depois, rode o instalador de novo."
        return (New-Result 'action_required' 'sessao do Claude Code nao verificada')
    }
    if ($auth.state -eq 'logged_out') {
        if ($Mode -eq 'check') { return (New-Result 'missing' 'Claude Code CLI sem login') }
        if ($Mode -eq 'plan') { return (New-Result 'would_configure' 'conduziria o login oficial (claude auth login)' ([ordered]@{ command = 'claude auth login' })) }
        $now = $Interactive -and (Read-YesNo 'O Claude Code esta sem login. Abrir agora o login oficial (claude auth login)? Ele espera voce concluir no navegador.')
        if (-not $now) {
            Request-Action -Step 'claude-cli-auth' -Id 'claude-login' -Kind 'run_in_terminal' -Command 'claude auth login' `
                -Message 'Faca login no Claude Code pelo fluxo oficial, num terminal: rode "claude auth login" e siga o navegador. Depois, rode o instalador de novo para conferir.'
            return (New-Result 'action_required' 'login do Claude Code pendente')
        }
        Invoke-Attached 'claude' @('auth', 'login') | Out-Null
        $auth = Get-ClaudeAuth
        if ($auth.state -ne 'logged_in') { return (New-Result 'failed' 'o login do Claude Code nao foi concluido') }
        $status = 'configured'
    }
    $data = [ordered]@{ authMethod = $auth.authMethod }
    if ($auth.configDirectory) {
        $data.configDirectory = $auth.configDirectory
        if ($auth.configDirectory.TrimEnd([char]92, [char]47) -ine $ConfigDir.TrimEnd([char]92, [char]47)) {
            Write-Log 'claude-cli-auth' 'warn' "O Claude Code usa $($auth.configDirectory), mas os agentes vao para $ConfigDir. Confira CLAUDE_CONFIG_DIR."
        }
    }
    $text = if ($status -eq 'already') { 'sessao do Claude Code ja estava valida' } else { 'login do Claude Code concluido' }
    return (New-Result $status "$text ($($auth.authMethod))" $data)
}

# --- claude-desktop -----------------------------------------------------------

function Test-ClaudeDesktop {
    switch ($env:HUBICG_STATION_TEST_DESKTOP) {
        'installed' { return $true }
        'absent' { return $false }
    }
    # The current installer deploys an MSIX package; older ones used Squirrel.
    # Get-AppxPackage fails in some sessions, so the package's execution alias
    # and its per-user registration are checked as well.
    try { if (Get-AppxPackage -Name 'AnthropicPBC.Claude' -ErrorAction Stop) { return $true } } catch { }
    if (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\AnthropicPBC.Claude_fnn82j28hfe8t')) { return $true }
    $packages = 'HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages'
    if (Get-ChildItem -LiteralPath $packages -ErrorAction SilentlyContinue | Where-Object { $_.PSChildName -like 'AnthropicPBC.Claude_*' }) { return $true }
    return (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'AnthropicClaude\claude.exe'))
}

function Step-ClaudeDesktop {
    if (Test-ClaudeDesktop) { return (New-Result 'already' 'Claude Desktop ja estava instalado') }
    # Official download links: https://claude.com/download
    $arch = if ($Script:Env.arch -eq 'ARM64') { 'arm64' } else { 'x64' }
    $url = "https://claude.ai/api/desktop/win32/$arch/setup/latest/redirect"
    if ($Mode -eq 'check') { return (New-Result 'missing' 'Claude Desktop nao instalado') }
    if ($Mode -eq 'plan') { return (New-Result 'would_install' 'baixaria o instalador oficial, conferiria a assinatura da Anthropic e o executaria' ([ordered]@{ url = $url })) }
    Send-Event -Type 'progress' -Step 'claude-desktop' -Message 'Baixando o Claude Desktop'
    $setup = Save-Download 'claude-desktop' $url 'Claude-Setup.exe'
    if (-not $setup) { return (New-Result 'failed' 'o download do Claude Desktop falhou') }
    try {
        $signature = Get-AuthenticodeSignature -LiteralPath $setup
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Anthropic') {
            return (New-Result 'failed' "assinatura do instalador do Claude Desktop invalida ($($signature.Status)); nada foi executado")
        }
        Start-Process -FilePath $setup -Wait
    } finally {
        Remove-Item -LiteralPath (Split-Path -Parent $setup) -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-ClaudeDesktop)) { return (New-Result 'failed' 'o instalador terminou, mas o Claude Desktop nao foi encontrado') }
    return (New-Result 'installed' 'Claude Desktop instalado')
}

# --- State file ---------------------------------------------------------------

function Read-State {
    $state = @{ agents = @{}; desktopLoginConfirmedAt = $null }
    if (Test-Path -LiteralPath $StateFile) {
        $raw = [IO.File]::ReadAllText($StateFile, $Utf8) | ConvertFrom-Json
        if (($raw.PSObject.Properties.Name -contains 'agents') -and $raw.agents) {
            foreach ($p in $raw.agents.PSObject.Properties) { $state.agents[$p.Name] = [string]$p.Value }
        }
        if ($raw.PSObject.Properties.Name -contains 'desktopLoginConfirmedAt') { $state.desktopLoginConfirmedAt = $raw.desktopLoginConfirmedAt }
    }
    return $state
}

function Write-State($State) {
    $agents = [ordered]@{}
    foreach ($key in ($State.agents.Keys | Sort-Object)) { $agents[$key] = $State.agents[$key] }
    $payload = [ordered]@{ schemaVersion = '1.0'; desktopLoginConfirmedAt = $State.desktopLoginConfirmedAt; agents = $agents }
    $text = ($payload | ConvertTo-Json -Depth 4) + "`n"
    # Unchanged state is not rewritten: a second run must not touch the disk.
    if ((Test-Path -LiteralPath $StateFile) -and ([IO.File]::ReadAllText($StateFile, $Utf8) -eq $text)) { return }
    New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
    $temporary = "$StateFile.tmp-$PID"
    [IO.File]::WriteAllText($temporary, $text, $Utf8)
    Move-Item -LiteralPath $temporary -Destination $StateFile -Force
}

function Step-ClaudeDesktopAuth {
    $state = Read-State
    if ($state.desktopLoginConfirmedAt) { return (New-Result 'already' "login no Claude Desktop confirmado em $($state.desktopLoginConfirmedAt)") }
    if ($Mode -eq 'check') { return (New-Result 'missing' 'login no Claude Desktop ainda nao confirmado') }
    if ($Mode -eq 'plan') { return (New-Result 'would_configure' 'abriria o Claude Desktop e pediria a confirmacao do login') }
    $confirmed = (Get-Answer 'desktop.loginConfirmed') -eq $true
    if (-not $confirmed -and $Interactive) {
        try { Start-Process 'shell:AppsFolder\AnthropicPBC.Claude_fnn82j28hfe8t!Claude' -ErrorAction Stop } catch { Write-Log 'claude-desktop-auth' 'info' 'Abra o Claude Desktop pelo menu Iniciar.' }
        $confirmed = Read-YesNo 'Faca o login no Claude Desktop. Concluiu?'
    }
    if (-not $confirmed) {
        Request-Action -Step 'claude-desktop-auth' -Id 'desktop-login-confirm' -Kind 'confirm' `
            -Message 'Abra o Claude Desktop, faca o login e confirme aqui. O instalador nao ve a sessao do app.' `
            -Answers @((New-Answer 'desktop.loginConfirmed' 'boolean' 'Concluí o login no Claude Desktop'))
        return (New-Result 'action_required' 'confirmacao do login no Claude Desktop pendente')
    }
    $state.desktopLoginConfirmedAt = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    Write-State $state
    return (New-Result 'configured' 'login no Claude Desktop confirmado pelo usuario')
}

# --- agents -------------------------------------------------------------------

function Get-Sha256([byte[]]$Bytes) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return (([BitConverter]::ToString($sha.ComputeHash($Bytes))) -replace '-', '').ToLowerInvariant() } finally { $sha.Dispose() }
}

function Test-ManagedAgent([string]$Text) {
    # Same rule as verify_claude_agent in scripts/build_station_agents.py.
    if (-not $Text.StartsWith("---`n")) { return $false }
    $end = $Text.IndexOf("`n---`n`n", 4)
    if ($end -lt 0) { return $false }
    $match = [regex]::Match($Text.Substring(4, $end - 4), '(?m)^# hubicg:managed role=[a-z0-9-]+ version=\S+ hash=sha256:([0-9a-f]{64})$')
    if (-not $match.Success) { return $false }
    return ((Get-Sha256 $Utf8.GetBytes($Text.Substring($end + 6))) -eq $match.Groups[1].Value)
}

function Step-Agents {
    if (-not (Test-Path -LiteralPath $AgentsSource)) {
        if ($Mode -ne 'apply') { return (New-Result $(if ($Mode -eq 'check') { 'missing' } else { 'would_install' }) "os agentes serao instalados de $AgentsSource depois do clone") }
        Request-Action -Step 'agents' -Id 'agents-export' -Kind 'external' -Message "Gere os agentes publicos: python scripts/build_station_agents.py (no clone $RepoDir); ou informe -AgentsSource com um export validado."
        return (New-Result 'action_required' "export publico de agentes ausente: $AgentsSource")
    }
    if ($DefaultAgentsSource) {
        $current = $false
        try {
            $libraryFile = Join-Path $RepoDir 'src\hubicg\library\manifest.json'
            $receiptFile = Join-Path $AgentsSource '.hubicg-station-export.json'
            $receipt = [IO.File]::ReadAllText($receiptFile, $Utf8) | ConvertFrom-Json -ErrorAction Stop
            $current = ($receipt.schema -is [string] -and
                $receipt.schema -eq 'hubicg.station.agents-export/1' -and
                $receipt.libraryManifestSha256 -is [string] -and
                $receipt.libraryManifestSha256 -eq (Get-Sha256 ([IO.File]::ReadAllBytes($libraryFile))))
        } catch { $current = $false }
        if (-not $current) {
            if ($Mode -ne 'apply') { return (New-Result $(if ($Mode -eq 'check') { 'missing' } else { 'would_install' }) 'export ausente, sem recibo ou desatualizado para a biblioteca do clone') }
            Request-Action -Step 'agents' -Id 'agents-export-stale' -Kind 'external' -Message "O export nao corresponde a biblioteca de $RepoDir. Preserve a pasta antiga com outro nome e gere um export novo no caminho padrao com Python 3.11+: python scripts/build_station_agents.py. Artefato externo explicito usa -AgentsSource e origem propria."
            return (New-Result 'action_required' 'export desatualizado ou sem origem verificavel no clone; nenhum agente foi alterado')
        }
    }
    $target = Join-Path $ConfigDir 'agents'
    $state = Read-State
    $counts = [ordered]@{ installed = 0; updated = 0; already = 0; removed = 0; conflict = 0 }
    $conflicts = @()
    $sources = @(Get-ChildItem -LiteralPath $AgentsSource -Filter '*.md' -File | Sort-Object Name)
    if ($sources.Count -eq 0) { return (New-Result 'failed' "nenhum agente em $AgentsSource") }
    $before = ($state.agents.Keys | Sort-Object | ForEach-Object { "$_=$($state.agents[$_])" }) -join ';'

    foreach ($file in $sources) {
        $bytes = [IO.File]::ReadAllBytes($file.FullName)
        if (-not (Test-ManagedAgent $Utf8.GetString($bytes))) {
            return (New-Result 'failed' "agente de origem corrompido ou editado a mao: $($file.Name). Nada foi instalado; atualize o clone.")
        }
    }
    if ($Mode -eq 'apply') {
        try { New-Item -ItemType Directory -Path $target -Force -ErrorAction Stop | Out-Null }
        catch { return (New-Result 'failed' "nao foi possivel criar ${target}: $($_.Exception.Message)") }
    }
    foreach ($file in $sources) {
        $bytes = [IO.File]::ReadAllBytes($file.FullName)
        $hash = Get-Sha256 $bytes
        $dest = Join-Path $target $file.Name
        $action = 'installed'
        if (Test-Path -LiteralPath $dest) {
            $current = Get-Sha256 ([IO.File]::ReadAllBytes($dest))
            if ($current -eq $hash) {
                $counts.already++
                if ($Mode -eq 'apply') { $state.agents[$file.Name] = $hash }
                continue
            }
            if (-not $state.agents.ContainsKey($file.Name) -or $state.agents[$file.Name] -ne $current) {
                # Not written by this installer, or edited after it was: never overwrite.
                $counts.conflict++
                $conflicts += $file.Name
                continue
            }
            $action = 'updated'
        }
        if ($Mode -eq 'apply') {
            $temporary = "$dest.tmp-$PID"
            try {
                [IO.File]::WriteAllBytes($temporary, $bytes)
                Move-Item -LiteralPath $temporary -Destination $dest -Force -ErrorAction Stop
            } catch {
                # Persist what did succeed, so the manifest never claims a file that is not there.
                Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
                Write-State $state
                return (New-Result 'failed' "nao foi possivel gravar ${dest}: $($_.Exception.Message)")
            }
            $state.agents[$file.Name] = $hash
        }
        $counts[$action]++
    }

    $names = @($sources | ForEach-Object { $_.Name })
    foreach ($name in @($state.agents.Keys)) {
        if ($names -contains $name) { continue }
        $dest = Join-Path $target $name
        if (-not (Test-Path -LiteralPath $dest)) {
            if ($Mode -eq 'apply') { $state.agents.Remove($name) }
        } elseif ((Get-Sha256 ([IO.File]::ReadAllBytes($dest))) -eq $state.agents[$name]) {
            if ($Mode -eq 'apply') { Remove-Item -LiteralPath $dest -Force; $state.agents.Remove($name) }
            $counts.removed++
        }
    }
    if ($Mode -eq 'apply') { Write-State $state }
    $after = ($state.agents.Keys | Sort-Object | ForEach-Object { "$_=$($state.agents[$_])" }) -join ';'

    foreach ($name in $conflicts) {
        Write-Log 'agents' 'warn' "$name ja existe em $target, nao foi instalado por este instalador (ou foi alterado depois) e foi mantido como estava."
    }
    $data = [ordered]@{ target = $target; source = $AgentsSource; sourceMode = $(if ($DefaultAgentsSource) { 'clone-library' } else { 'external' }); total = $sources.Count; counts = $counts; conflicts = @($conflicts) }
    $summary = "$($sources.Count) agentes: $($counts.installed) novos, $($counts.updated) atualizados, $($counts.already) iguais, $($counts.removed) removidos, $($counts.conflict) conflitos mantidos"
    if (($counts.installed + $counts.updated + $counts.removed) -eq 0) {
        # Adopting identical files into a new manifest is still a change on disk.
        if ($Mode -eq 'apply' -and $before -ne $after) { return (New-Result 'configured' "$summary; manifesto atualizado" $data) }
        return (New-Result 'already' $summary $data)
    }
    if ($Mode -eq 'check') { return (New-Result 'missing' $summary $data) }
    if ($Mode -eq 'plan') { return (New-Result 'would_install' $summary $data) }
    return (New-Result $(if ($counts.installed -gt 0) { 'installed' } else { 'updated' }) $summary $data)
}

# --- Runner -------------------------------------------------------------------

$Handlers = @{
    'environment' = { Step-Environment }; 'git' = { Step-Git }; 'git-identity' = { Step-GitIdentity }
    'gh' = { Step-Gh }; 'gh-auth' = { Step-GhAuth }; 'repo' = { Step-Repo }
    'claude-cli' = { Step-ClaudeCli }; 'claude-cli-auth' = { Step-ClaudeCliAuth }
    'claude-desktop' = { Step-ClaudeDesktop }; 'claude-desktop-auth' = { Step-ClaudeDesktopAuth }
    'agents' = { Step-Agents }
}

$Only = @($Only | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$unknown = @($Only | Where-Object { $AllSteps -notcontains $_ })
if ($unknown.Count -gt 0) {
    [Console]::Error.WriteLine('Etapa desconhecida: ' + ($unknown -join ', ') + '. Validas: ' + ($AllSteps -join ', '))
    exit 2
}

Send-Event -Type 'run_start' -Message "HubICG station $EngineVersion" -Data ([ordered]@{
    engine = $EngineVersion; contract = 1; mode = $Mode; os = 'windows'; interactive = $Interactive
    steps = $AllSteps; repoDir = $RepoDir; configDir = $ConfigDir; logFile = $LogFile
})

if ($PSVersionTable.PSVersion.Major -lt 5 -or [Environment]::OSVersion.Platform -ne 'Win32NT') {
    Send-Event -Type 'run_end' -Status 'exit_4' -Message 'Este motor exige Windows com PowerShell 5.1 ou superior. Em Linux e macOS, use hubicg-station.sh.' -Data ([ordered]@{ exitCode = 4; steps = @{} })
    exit 4
}

$index = 0
foreach ($step in $AllSteps) {
    $index++
    Send-Event -Type 'step_start' -Step $step -Data ([ordered]@{ index = $index; total = $AllSteps.Count })
    if ($Only.Count -gt 0 -and $step -ne 'environment' -and $Only -notcontains $step) {
        $result = New-Result 'skipped' 'fora da selecao de -Only'
    } else {
        $blockedBy = @($Depends[$step] | Where-Object { $_ -and $Results.Contains($_) -and $Results[$_].status -in @('failed', 'action_required', 'blocked') })
        if ($Mode -eq 'apply' -and $blockedBy.Count -gt 0) {
            $result = New-Result 'blocked' ('depende de: ' + ($blockedBy -join ', ')) ([ordered]@{ blockedBy = $blockedBy })
        } else {
            try {
                $result = & $Handlers[$step]
            } catch {
                $result = New-Result 'failed' ('erro inesperado: ' + $_.Exception.Message)
            }
        }
    }
    $Results[$step] = $result
    Send-Event -Type 'step_end' -Step $step -Status $result.status -Message $result.message -Data $result.data
}

$statuses = @($Results.Values | ForEach-Object { $_.status })
$exitCode = 0
if ($statuses -contains 'failed') { $exitCode = 1 }
elseif (($statuses -contains 'action_required') -or ($statuses -contains 'blocked')) { $exitCode = 3 }
elseif (@($statuses | Where-Object { $_ -in @('missing', 'would_install', 'would_configure', 'would_update') }).Count -gt 0) { $exitCode = 5 }

$summary = [ordered]@{}
foreach ($key in $Results.Keys) { $summary[$key] = $Results[$key].status }
$final = switch ($exitCode) {
    0 { 'Concluido: nada pendente.' }
    1 { 'Terminou com falha; veja as etapas marcadas como failed.' }
    3 { 'Ha acoes suas pendentes; conclua-as e rode o instalador de novo.' }
    5 { 'Ha itens a instalar ou configurar; rode sem -Check/-WhatIf para aplicar.' }
}
Send-Event -Type 'run_end' -Status $(if ($exitCode -eq 0) { 'ok' } else { "exit_$exitCode" }) -Message $final -Data ([ordered]@{ exitCode = $exitCode; steps = $summary })
exit $exitCode
