#Requires -Version 5.1
<#
.SYNOPSIS
  Assistente gráfico (W1, WinForms) do instalador da estação HubICG no Windows.

.DESCRIPTION
  Conduz o motor installers\station\hubicg-station.ps1 pelo contrato hubicg.station.event/1
  (docs\architecture\station-installer-engine.md): roda a verificação, mostra o ambiente, deixa escolher as
  etapas e a pasta do clone, acompanha a instalação pelos eventos JSON, conduz os pedidos de ação (inclusive os
  logins, sempre pelo fluxo oficial) e mostra o resumo com o caminho do log.

  O assistente não instala nada por conta própria e nunca pede senha ou token. Responde ao motor por arquivo
  de respostas e nova execução, como o contrato define.

  Ponto de entrada de clique duplo: Instalar-HubICG-Estacao.cmd, na mesma pasta.

.PARAMETER EnginePath
  Motor a conduzir. Padrão: ..\..\hubicg-station.ps1. Aceita o motor simulado dos testes (.py).

.PARAMETER CaptureDir
  Pasta para salvar uma captura de tela de cada passo (evidência e testes). Opcional.
#>
[CmdletBinding()]
param(
  [string]$EnginePath = $env:HUBICG_STATION_ENGINE,
  [string]$CaptureDir = $env:HUBICG_STATION_UI_CAPTURE
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'StationUi.Core.ps1')

if ([System.Threading.Thread]::CurrentThread.GetApartmentState() -ne [System.Threading.ApartmentState]::STA) {
  # WinForms exige STA (área de transferência e seletor de pasta). Reabre o próprio script nesse modo.
  $relaunch = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA', '-File', $PSCommandPath)
  if ($EnginePath) { $relaunch += @('-EnginePath', $EnginePath) }
  if ($CaptureDir) { $relaunch += @('-CaptureDir', $CaptureDir) }
  $line = ($relaunch | ForEach-Object { ConvertTo-StationArgument $_ }) -join ' '
  Start-Process -FilePath 'powershell.exe' -ArgumentList $line -Wait
  exit
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -Namespace HubIcg -Name StationNative -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern bool SetProcessDPIAware();
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern bool PrintWindow(System.IntPtr hwnd, System.IntPtr hdc, uint flags);
'@
[void][HubIcg.StationNative]::SetProcessDPIAware()
[System.Windows.Forms.Application]::EnableVisualStyles()

$script:Texts = Import-StationTexts
if (-not $EnginePath) { $EnginePath = Join-Path $PSScriptRoot '..\..\hubicg-station.ps1' }
$script:EnginePath = [System.IO.Path]::GetFullPath($EnginePath)
$script:CaptureDir = $CaptureDir
$script:CaptureIndex = 0
$script:Run = $null
$script:CheckState = $null
$script:LastState = $null
$script:Selection = @()
$script:RepoDir = $null
$script:PrimaryAction = $null
$script:SecondaryAction = $null
$script:Closing = $false
$script:InTick = $false
$script:Session = $null
$script:LastStderr = ''
$script:CodeDeadline = $null
$script:CodeUrl = $null
$script:StatusLabel = $null

$fontBody = New-Object System.Drawing.Font('Segoe UI', 10)
$fontBold = New-Object System.Drawing.Font('Segoe UI', 10, [System.Drawing.FontStyle]::Bold)
$fontTitle = New-Object System.Drawing.Font('Segoe UI Semibold', 15)
$fontCode = New-Object System.Drawing.Font('Consolas', 26, [System.Drawing.FontStyle]::Bold)
$fontMono = New-Object System.Drawing.Font('Consolas', 9.5)

# --- janela ---------------------------------------------------------------------------------------

$form = New-Object System.Windows.Forms.Form
$form.Text = $script:Texts.product
$form.Font = $fontBody
$form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::Dpi
$form.StartPosition = 'CenterScreen'
$form.Size = New-Object System.Drawing.Size(900, 680)
$form.MinimumSize = New-Object System.Drawing.Size(720, 520)
$form.KeyPreview = $true

$layout = New-Object System.Windows.Forms.TableLayoutPanel
$layout.Dock = 'Fill'
$layout.ColumnCount = 1
$layout.RowCount = 3
[void]$layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
[void]$layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
$form.Controls.Add($layout)

$header = New-Object System.Windows.Forms.TableLayoutPanel
$header.Dock = 'Fill'
$header.AutoSize = $true
$header.ColumnCount = 1
$header.Padding = New-Object System.Windows.Forms.Padding(16, 12, 16, 8)
$header.BackColor = [System.Drawing.SystemColors]::Window
$headerTitle = New-Object System.Windows.Forms.Label
$headerTitle.AutoSize = $true
$headerTitle.Font = $fontTitle
$headerTitle.Name = 'TituloDoPasso'
$headerStep = New-Object System.Windows.Forms.Label
$headerStep.AutoSize = $true
$headerStep.Name = 'IndicadorDePasso'
$headerStep.ForeColor = [System.Drawing.SystemColors]::GrayText
$header.Controls.Add($headerTitle)
$header.Controls.Add($headerStep)
$layout.Controls.Add($header, 0, 0)

$content = New-Object System.Windows.Forms.Panel
$content.Dock = 'Fill'
$layout.Controls.Add($content, 0, 1)

$footer = New-Object System.Windows.Forms.FlowLayoutPanel
$footer.Dock = 'Fill'
$footer.AutoSize = $true
$footer.FlowDirection = 'RightToLeft'
$footer.Padding = New-Object System.Windows.Forms.Padding(12, 8, 12, 12)
$layout.Controls.Add($footer, 0, 2)

function New-FooterButton {
  param([string]$Name)
  $button = New-Object System.Windows.Forms.Button
  $button.Name = $Name
  $button.AutoSize = $true
  $button.MinimumSize = New-Object System.Drawing.Size(120, 34)
  $button.Padding = New-Object System.Windows.Forms.Padding(8, 2, 8, 2)
  return $button
}
$btnPrimary = New-FooterButton 'BotaoPrincipal'
$btnSecondary = New-FooterButton 'BotaoSecundario'
$btnCancel = New-FooterButton 'BotaoCancelar'
$footer.Controls.AddRange(@($btnPrimary, $btnSecondary, $btnCancel))
$form.AcceptButton = $btnPrimary

$btnPrimary.add_Click({ if ($script:PrimaryAction) { Invoke-Safely $script:PrimaryAction } })
$btnSecondary.add_Click({ if ($script:SecondaryAction) { Invoke-Safely $script:SecondaryAction } })
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 100

# --- utilidades de tela ---------------------------------------------------------------------------

function Invoke-Safely {
  param([scriptblock]$Action)
  try { & $Action }
  catch {
    [void][System.Windows.Forms.MessageBox]::Show($form,
      "Erro inesperado no assistente:`r`n`r`n$($_.Exception.Message)",
      $script:Texts.product, 'OK', 'Error')
  }
}

function Set-Header {
  param([int]$Number, [string]$Title)
  $names = 'Boas-vindas', 'Verificação', 'Seleção', 'Instalação', 'Resumo'
  $headerTitle.Text = $Title
  $headerStep.Text = 'Passo {0} de 5: {1}' -f $Number, $names[$Number - 1]
  $form.Text = '{0} — {1}' -f $script:Texts.product, $names[$Number - 1]
}

function Set-Buttons {
  # Configura o rodapé. Botão sem texto fica escondido.
  param([string]$Primary, [scriptblock]$OnPrimary, [string]$Secondary, [scriptblock]$OnSecondary,
    [string]$Cancel = 'Cancelar')
  $script:PrimaryAction = $OnPrimary
  $script:SecondaryAction = $OnSecondary
  $btnPrimary.Text = $Primary; $btnPrimary.Visible = [bool]$Primary; $btnPrimary.Enabled = $true
  $btnSecondary.Text = $Secondary; $btnSecondary.Visible = [bool]$Secondary; $btnSecondary.Enabled = $true
  $btnCancel.Text = $Cancel; $btnCancel.Visible = [bool]$Cancel; $btnCancel.Enabled = $true
}

function New-Page {
  # Página em pilha vertical: rótulos quebram linha e os demais controles ocupam a largura toda.
  $content.SuspendLayout()
  foreach ($old in @($content.Controls)) { $content.Controls.Remove($old); $old.Dispose() }
  $stack = New-Object System.Windows.Forms.FlowLayoutPanel
  $stack.Name = 'Pagina'
  $stack.Dock = 'Fill'
  $stack.FlowDirection = 'TopDown'
  $stack.WrapContents = $false
  $stack.AutoScroll = $true
  $stack.Padding = New-Object System.Windows.Forms.Padding(16, 8, 16, 8)
  $stack.add_Resize({ Update-PageWidth $this })
  $stack.add_ControlAdded({ Update-PageWidth $this })
  $content.Controls.Add($stack)
  $content.ResumeLayout()
  return $stack
}

function Update-PageWidth {
  param($Stack)
  $width = $Stack.ClientSize.Width - $Stack.Padding.Horizontal - [System.Windows.Forms.SystemInformation]::VerticalScrollBarWidth
  if ($width -lt 200) { return }
  foreach ($child in $Stack.Controls) {
    $inner = $width - $child.Margin.Horizontal
    if ($child.Tag -eq 'wrap') { $child.MaximumSize = New-Object System.Drawing.Size($inner, 0) }
    elseif ($child.Tag -ne 'fixed') { $child.Width = $inner }
  }
}

function Add-Text {
  param($Stack, [string]$Text, [System.Drawing.Font]$Font = $fontBody, [string]$Name, [int]$SpaceAfter = 6)
  $label = New-Object System.Windows.Forms.Label
  $label.AutoSize = $true
  $label.Tag = 'wrap'
  $label.Font = $Font
  $label.Text = $Text
  $label.UseMnemonic = $false
  $label.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, $SpaceAfter)
  if ($Name) { $label.Name = $Name }
  $Stack.Controls.Add($label)
  return $label
}

function Add-Row {
  # Linha de botões lado a lado dentro da pilha.
  param($Stack)
  $row = New-Object System.Windows.Forms.FlowLayoutPanel
  $row.AutoSize = $true
  $row.WrapContents = $true
  $row.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, 8)
  $Stack.Controls.Add($row)
  return $row
}

function Add-Button {
  param($Row, [string]$Text, [string]$Name, [scriptblock]$OnClick)
  $button = New-Object System.Windows.Forms.Button
  $button.Text = $Text
  $button.Name = $Name
  $button.AutoSize = $true
  $button.MinimumSize = New-Object System.Drawing.Size(0, 32)
  $button.add_Click($OnClick)
  $Row.Controls.Add($button)
  return $button
}

function New-ListView {
  param($Stack, [string]$Name, [string]$AccessibleName, [object[]]$Columns, [int]$Height = 220)
  $list = New-Object System.Windows.Forms.ListView
  $list.Name = $Name
  $list.AccessibleName = $AccessibleName
  $list.View = 'Details'
  $list.FullRowSelect = $true
  $list.HideSelection = $false
  $list.MultiSelect = $false
  $list.HeaderStyle = 'Nonclickable'
  $list.Height = $Height
  foreach ($column in $Columns) { [void]$list.Columns.Add($column[0], $column[1]) }
  $Stack.Controls.Add($list)
  return $list
}

function Add-ListItem {
  param($List, [string[]]$Values, $Group, $Tag)
  $item = New-Object System.Windows.Forms.ListViewItem($Values[0])
  for ($i = 1; $i -lt $Values.Count; $i++) { [void]$item.SubItems.Add([string]$Values[$i]) }
  if ($Group) { $item.Group = $Group }
  $item.Tag = $Tag
  [void]$List.Items.Add($item)
  return $item
}

function Save-Capture {
  # Evidência: a janela do assistente desenhada por ela mesma (PrintWindow), nunca uma cópia da tela, para não
  # capturar outra janela que esteja por cima. Sem DoEvents aqui: ele reentraria no Timer do motor.
  param([string]$Name)
  if (-not $script:CaptureDir) { return }
  if (-not (Test-Path -LiteralPath $script:CaptureDir)) { New-Item -ItemType Directory -Path $script:CaptureDir | Out-Null }
  $form.Refresh()
  $bounds = $form.Bounds
  $bitmap = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  $hdc = $graphics.GetHdc()
  [void][HubIcg.StationNative]::PrintWindow($form.Handle, $hdc, 2)
  $graphics.ReleaseHdc($hdc)
  $script:CaptureIndex++
  $file = Join-Path $script:CaptureDir ('{0:D2}-{1}.png' -f $script:CaptureIndex, $Name)
  $bitmap.Save($file, [System.Drawing.Imaging.ImageFormat]::Png)
  $graphics.Dispose(); $bitmap.Dispose()
}

function Open-Url {
  param([string]$Url)
  if ($Url -notmatch '^https://') { return }
  Start-Process -FilePath $Url
}

function Set-ClipboardText {
  param([string]$Text, [string]$What)
  [System.Windows.Forms.Clipboard]::SetText($Text)
  $script:StatusLabel.Text = "$What copiado para a área de transferência."
}

function Get-FreshPath {
  # O motor pode ter mudado o PATH do usuário durante a instalação; este processo ainda tem o antigo.
  $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $user = [Environment]::GetEnvironmentVariable('Path', 'User')
  return (@($machine, $user) | Where-Object { $_ }) -join ';'
}

function Open-Terminal {
  param([string]$Command)
  [void](Start-StationTerminal -Command $Command -Path (Get-FreshPath))
}

# --- execução do motor ----------------------------------------------------------------------------

function Start-EngineRun {
  # Roda o motor sem travar a janela: lê stdout de forma assíncrona e consome as linhas num Timer da UI.
  param([string[]]$Arguments, [scriptblock]$OnEvent, [scriptblock]$OnExit, [string]$AnswersFile)
  try {
    $invocation = Get-StationEngineInvocation -EnginePath $script:EnginePath -Arguments $Arguments
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $invocation.FileName
    $info.Arguments = $invocation.CommandLine
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $info.StandardErrorEncoding = New-Object System.Text.UTF8Encoding($false)
    $process = [System.Diagnostics.Process]::Start($info)
    $script:Run = @{
      Process     = $process
      Pending     = $process.StandardOutput.ReadLineAsync()
      Stderr      = $process.StandardError.ReadToEndAsync()
      State       = New-StationRunState
      OnEvent     = $OnEvent
      OnExit      = $OnExit
      AnswersFile = $AnswersFile
    }
    $timer.Start()
  }
  catch {
    if ($script:Run) { Stop-StationEngineRun $script:Run }
    else { Remove-StationRunAnswers @{ AnswersFile = $AnswersFile } }
    throw
  }
}

function Stop-EngineRun {
  # Encerra o motor e os processos filhos (o fluxo oficial de login, por exemplo). A próxima execução recomeça a etapa.
  Stop-StationEngineRun $script:Run
}

$timer.add_Tick({
    $run = $script:Run
    if (-not $run) { $timer.Stop(); return }
    if ($script:InTick) { return }
    $script:InTick = $true
    try {
      $count = 0
      while ($run.Pending -and $run.Pending.IsCompleted -and $count -lt 200) {
        $line = $run.Pending.Result
        if ($null -eq $line) { $run.Pending = $null; break }
        $run.Pending = $run.Process.StandardOutput.ReadLineAsync()
        $stationEvent = ConvertFrom-StationEventLine $line
        $type = Update-StationRunState $run.State $stationEvent
        if ($type -and $run.OnEvent) { & $run.OnEvent $run.State $stationEvent $type }
        $count++
      }
      if ($run.State.Blocking) { Update-CodeCountdown }
      if ($null -eq $run.Pending -and $run.Process.HasExited) {
        $timer.Stop()
        $run.Process.WaitForExit()
        [void](Complete-StationRunState $run.State $run.Process.ExitCode)
        $run.StderrText = $run.Stderr.Result
        Remove-StationRunAnswers $run
        $script:Run = $null
        if (-not $script:Closing) { & $run.OnExit $run }
      }
    }
    catch {
      $timer.Stop()
      Stop-EngineRun
      [void][System.Windows.Forms.MessageBox]::Show($form, "Erro ao ler o instalador:`r`n$($_.Exception.Message)",
        $script:Texts.product, 'OK', 'Error')
    }
    finally { $script:InTick = $false }
  })

# --- passo 1: boas-vindas -------------------------------------------------------------------------

function Show-WelcomePage {
  Set-Header 1 $script:Texts.welcome.title
  $page = New-Page
  foreach ($paragraph in $script:Texts.welcome.body) { [void](Add-Text $page $paragraph -SpaceAfter 10) }
  [void](Add-Text $page ('Instalador usado: {0}' -f $script:EnginePath) -Name 'CaminhoDoMotor')
  Set-Buttons -Primary 'Verificar o computador' -OnPrimary { Show-CheckPage }
  $btnPrimary.Focus()
  Save-Capture 'boas-vindas'
}

# --- passo 2: verificação -------------------------------------------------------------------------

function Show-CheckPage {
  Set-Header 2 'Verificando o computador'
  $page = New-Page
  [void](Add-Text $page 'Estamos conferindo o sistema, a rede e as ferramentas. Nada é instalado nesta etapa.')
  $bar = New-Object System.Windows.Forms.ProgressBar
  $bar.Style = 'Marquee'
  $bar.Height = 18
  $bar.AccessibleName = 'Verificação em andamento'
  $page.Controls.Add($bar)
  Set-Buttons
  $btnCancel.Text = 'Cancelar'; $btnCancel.Visible = $true
  Start-EngineRun -Arguments (Get-StationEngineArguments -Mode check) -OnExit {
    param($run)
    $script:CheckState = $run.State
    Show-CheckResult $run
  }
}

function Show-CheckResult {
  param($Run)
  $state = $Run.State
  $code = [int]$state.ExitCode
  $page = New-Page
  if ($code -in 2, 4) {
    Set-Header 2 'Não é possível continuar'
    [void](Add-Text $page (Get-StationExitMessage $script:Texts $code) -Font $fontBold)
    if ($Run.StderrText) { [void](Add-Text $page $Run.StderrText.Trim() -Font $fontMono) }
    Set-Buttons -Cancel 'Fechar'
    Save-Capture 'verificacao-sem-suporte'
    return
  }
  Set-Header 2 'Resultado da verificação'
  [void](Add-Text $page (Get-StationExitMessage $script:Texts $code) -Font $fontBold)
  [void](Add-Text $page 'Ambiente' -Font $fontBold -SpaceAfter 2)
  $envList = New-ListView $page 'ListaAmbiente' 'Ambiente do computador' @(@('Item', 230), @('Situação', 260), @('Atenção', 120)) 210
  foreach ($row in (Get-StationEnvironmentRows $script:Texts $state.Environment)) {
    $attention = @{ ok = 'OK'; info = 'Informação'; warn = 'Aviso'; error = 'Problema' }[$row.Severity]
    [void](Add-ListItem $envList @($row.Item, $row.Value, $attention) $null $row.Explain)
  }
  [void](Add-Text $page 'Etapas' -Font $fontBold -SpaceAfter 2)
  $stepList = New-ListView $page 'ListaEtapasVerificadas' 'Situação de cada etapa' @(@('Etapa', 260), @('Situação', 220), @('Detalhe', 300)) 200
  foreach ($step in $state.Steps) {
    if ($step -eq 'environment' -or -not $state.Status.ContainsKey($step)) { continue }
    $info = Get-StationStatusInfo $script:Texts $state.Status[$step]
    [void](Add-ListItem $stepList @((Get-StationStepLabel $script:Texts $step), $info.Label, $state.Messages[$step]) $null $state.Messages[$step])
  }
  [void](Add-Text $page 'Explicação do item selecionado' -Font $fontBold -SpaceAfter 2)
  $detail = New-Object System.Windows.Forms.TextBox
  $script:CheckDetail = $detail
  $detail.Name = 'ExplicacaoDoItem'
  $detail.AccessibleName = 'Explicação do item selecionado'
  $detail.Multiline = $true
  $detail.ReadOnly = $true
  $detail.ScrollBars = 'Vertical'
  $detail.Height = 70
  $warnings = @($state.Logs | Where-Object { $_.Level -in 'warn', 'error' } | ForEach-Object { $_.Message })
  if ($warnings.Count -gt 0) { $detail.Text = $warnings -join "`r`n`r`n" }
  else { $detail.Text = 'Selecione um item da lista para ver a explicação.' }
  $page.Controls.Add($detail)
  $showDetail = {
    $selected = @($this.SelectedItems)
    if ($selected.Count -gt 0) {
      $text = [string]$selected[0].Tag
      if (-not $text) { $text = 'Nada a explicar: o item está em ordem.' }
      $script:CheckDetail.Text = $text
    }
  }
  $envList.add_SelectedIndexChanged($showDetail)
  $stepList.add_SelectedIndexChanged($showDetail)
  Set-Buttons -Primary 'Avançar' -OnPrimary { Show-SelectionPage } -Secondary 'Verificar de novo' -OnSecondary { Show-CheckPage }
  $envList.Focus()
  Save-Capture 'verificacao'
}

# --- passo 3: seleção -----------------------------------------------------------------------------

function Show-SelectionPage {
  Set-Header 3 'O que instalar'
  $state = $script:CheckState
  $page = New-Page
  [void](Add-Text $page 'Marque as etapas que o instalador deve executar. O padrão é tudo: o que já estiver pronto não é refeito.')
  $list = New-Object System.Windows.Forms.CheckedListBox
  $script:SelList = $list
  $list.Name = 'ListaDeEtapas'
  $list.AccessibleName = 'Etapas a executar'
  $list.CheckOnClick = $true
  $list.IntegralHeight = $false
  $list.Height = 230
  $defaults = Get-StationDefaultSelection $state
  $current = $script:Selection
  if (-not $current -or $current.Count -eq 0) { $current = $defaults }
  $map = New-Object System.Collections.ArrayList
  $script:SelMap = $map
  $notApplicable = @()
  foreach ($step in $state.Steps) {
    if ($step -eq 'environment') { continue }
    $status = $state.Status[$step]
    if ($status -eq 'unsupported') { $notApplicable += (Get-StationStepLabel $script:Texts $step); continue }
    $info = Get-StationStatusInfo $script:Texts $status
    $index = $list.Items.Add(('{0} — {1}' -f (Get-StationStepLabel $script:Texts $step), $info.Label))
    $list.SetItemChecked($index, $current -contains $step)
    [void]$map.Add($step)
  }
  $page.Controls.Add($list)
  if ($notApplicable.Count -gt 0) {
    [void](Add-Text $page ('Não se aplicam a este sistema: {0}.' -f ($notApplicable -join ', ')))
  }
  $row = Add-Row $page
  $row.Tag = 'fixed'
  [void](Add-Button $row '&Marcar tudo' 'MarcarTudo' { Set-AllSteps $true })
  [void](Add-Button $row '&Desmarcar tudo' 'DesmarcarTudo' { Set-AllSteps $false })

  $dirLabel = Add-Text $page '&Pasta do clone do repositório' -Font $fontBold -SpaceAfter 2
  $dirLabel.UseMnemonic = $true
  $dirRow = New-Object System.Windows.Forms.TableLayoutPanel
  $dirRow.ColumnCount = 2
  $dirRow.Height = 36
  [void]$dirRow.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 100)))
  [void]$dirRow.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::AutoSize)))
  $dirBox = New-Object System.Windows.Forms.TextBox
  $script:DirBox = $dirBox
  $dirBox.Name = 'PastaDoClone'
  $dirBox.AccessibleName = 'Pasta do clone do repositório'
  $dirBox.Dock = 'Fill'
  $dirBox.Text = $(if ($script:RepoDir) { $script:RepoDir } else { $state.RepoDir })
  $browse = New-Object System.Windows.Forms.Button
  $browse.Text = 'Escolher…'
  $browse.Name = 'EscolherPasta'
  $browse.AutoSize = $true
  $browse.add_Click({ Select-RepoFolder })
  $dirRow.Controls.Add($dirBox, 0, 0)
  $dirRow.Controls.Add($browse, 1, 0)
  $page.Controls.Add($dirRow)

  [void](Add-Text $page 'Como serão os logins' -Font $fontBold -SpaceAfter 2)
  foreach ($property in $script:Texts.authPreview.PSObject.Properties) {
    [void](Add-Text $page ('• ' + $property.Value) -SpaceAfter 2)
  }
  [void](Add-Text $page 'Nenhuma senha ou token é digitado neste assistente.' -SpaceAfter 8)

  Set-Buttons -Primary 'Instalar' -OnPrimary { Start-Selection } -Secondary 'Voltar' -OnSecondary { Show-CheckResult @{ State = $script:CheckState; StderrText = '' } }
  $list.Focus()
  Save-Capture 'selecao'
}

function Set-AllSteps {
  param([bool]$Checked)
  for ($i = 0; $i -lt $script:SelList.Items.Count; $i++) { $script:SelList.SetItemChecked($i, $Checked) }
}

function Select-RepoFolder {
  $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
  $dialog.Description = 'Escolha a pasta onde o repositório HubICG Community será clonado.'
  $dialog.ShowNewFolderButton = $true
  $parent = Split-Path -Parent $script:DirBox.Text
  if ($parent -and (Test-Path -LiteralPath $parent)) { $dialog.SelectedPath = $parent }
  if ($dialog.ShowDialog($form) -eq 'OK') { $script:DirBox.Text = Join-Path $dialog.SelectedPath 'hubicg-community' }
}

function Start-Selection {
  $chosen = @()
  for ($i = 0; $i -lt $script:SelList.Items.Count; $i++) {
    if ($script:SelList.GetItemChecked($i)) { $chosen += $script:SelMap[$i] }
  }
  if ($chosen.Count -eq 0) {
    [void][System.Windows.Forms.MessageBox]::Show($form, 'Marque pelo menos uma etapa.', $script:Texts.product, 'OK', 'Information')
    $script:SelList.Focus(); return
  }
  if ([string]::IsNullOrWhiteSpace($script:DirBox.Text)) {
    [void][System.Windows.Forms.MessageBox]::Show($form, 'Informe a pasta do clone.', $script:Texts.product, 'OK', 'Information')
    $script:DirBox.Focus(); return
  }
  $script:Selection = $chosen
  $script:RepoDir = $script:DirBox.Text.Trim()
  Show-RunPage -NewSession
}

# --- passo 4: instalação --------------------------------------------------------------------------

function Show-RunPage {
  # -NewSession: instalação nova (seleção ou "Rodar de novo"). Sem ele, continua a sessão depois das pendências.
  param([string]$AnswersFile, [switch]$NewSession)
  if ($NewSession -or -not $script:Session) { $script:Session = New-StationSession }
  Set-Header 4 'Instalando e configurando'
  $page = New-Page
  $script:CurrentLabel = Add-Text $page 'Iniciando o instalador…' -Font $fontBold -Name 'EtapaAtual'
  if ($script:CurrentLabel.PSObject.Properties['LiveSetting']) {
    $script:CurrentLabel.LiveSetting = [System.Windows.Forms.Automation.AutomationLiveSetting]::Polite
  }
  $script:OverallBar = New-Object System.Windows.Forms.ProgressBar
  $script:OverallBar.Name = 'ProgressoGeral'
  $script:OverallBar.AccessibleName = 'Progresso geral'
  $script:OverallBar.Height = 20
  $page.Controls.Add($script:OverallBar)
  $script:StepBar = New-Object System.Windows.Forms.ProgressBar
  $script:StepBar.Name = 'ProgressoDaEtapa'
  $script:StepBar.AccessibleName = 'Progresso da etapa atual'
  $script:StepBar.Height = 10
  $page.Controls.Add($script:StepBar)

  # Painel do código de dispositivo (browser_code): aparece só enquanto o motor espera o login no navegador.
  $script:CodePanel = New-Object System.Windows.Forms.GroupBox
  $script:CodePanel.Name = 'PainelDoCodigo'
  $script:CodePanel.Text = 'Login no navegador'
  $script:CodePanel.Height = 210
  $script:CodePanel.Visible = $false
  $codeStack = New-Object System.Windows.Forms.FlowLayoutPanel
  $codeStack.Dock = 'Fill'
  $codeStack.FlowDirection = 'TopDown'
  $codeStack.WrapContents = $false
  $codeStack.Padding = New-Object System.Windows.Forms.Padding(8)
  $script:CodeMessage = New-Object System.Windows.Forms.Label
  $script:CodeMessage.AutoSize = $true
  $script:CodeMessage.MaximumSize = New-Object System.Drawing.Size(780, 0)
  $script:CodeBox = New-Object System.Windows.Forms.TextBox
  $script:CodeBox.Name = 'CodigoDeDispositivo'
  $script:CodeBox.AccessibleName = 'Código de dispositivo'
  $script:CodeBox.ReadOnly = $true
  $script:CodeBox.BorderStyle = 'None'
  $script:CodeBox.Font = $fontCode
  $script:CodeBox.Width = 420
  $script:CodeBox.BackColor = [System.Drawing.SystemColors]::Control
  $codeRow = New-Object System.Windows.Forms.FlowLayoutPanel
  $codeRow.AutoSize = $true
  $script:CodeCopy = Add-Button $codeRow '&Copiar código' 'CopiarCodigo' { Set-ClipboardText $script:CodeBox.Text 'Código' }
  $script:CodeOpen = Add-Button $codeRow '&Abrir a página de login' 'AbrirPaginaDeLogin' { Open-Url $script:CodeUrl }
  $script:CodeCountdown = New-Object System.Windows.Forms.Label
  $script:CodeCountdown.AutoSize = $true
  $script:CodeCountdown.Name = 'TempoDoCodigo'
  $codeStack.Controls.AddRange(@($script:CodeMessage, $script:CodeBox, $codeRow, $script:CodeCountdown))
  $script:CodePanel.Controls.Add($codeStack)
  $page.Controls.Add($script:CodePanel)

  $script:RunList = New-ListView $page 'ListaDeProgresso' 'Andamento das etapas' @(@('Etapa', 260), @('Situação', 200), @('Detalhe', 320)) 230
  $script:RunRows = @{}
  $script:DetailsBox = New-Object System.Windows.Forms.TextBox
  $script:DetailsBox.Name = 'Detalhes'
  $script:DetailsBox.AccessibleName = 'Detalhes da execução'
  $script:DetailsBox.Multiline = $true
  $script:DetailsBox.ReadOnly = $true
  $script:DetailsBox.ScrollBars = 'Vertical'
  $script:DetailsBox.Font = $fontMono
  $script:DetailsBox.Height = 90
  $page.Controls.Add($script:DetailsBox)
  $script:StatusLabel = Add-Text $page '' -Name 'Aviso'

  Set-Buttons -Primary 'Instalando…' -OnPrimary $null -Cancel 'Interromper'
  $btnPrimary.Enabled = $false
  $script:ProgressCaptured = $false
  # Seleção padrão vai sem -Only, para o motor reportar "unsupported" e não "skipped".
  $only = $script:Selection
  $defaults = Get-StationDefaultSelection $script:CheckState
  if (-not (Compare-Object @($defaults) @($script:Selection))) { $only = @() }
  $arguments = Get-StationEngineArguments -Mode apply -Only $only -RepoDir $script:RepoDir -AnswersFile $AnswersFile
  Start-EngineRun -Arguments $arguments -AnswersFile $AnswersFile -OnEvent {
    param($state, $event, $type)
    Update-RunView $state $event $type
  } -OnExit {
    param($run)
    $script:LastState = Merge-StationSession $script:Texts $script:Session $run.State
    $script:LastStderr = $run.StderrText
    $script:CodePanel.Visible = $false
    if ($run.State.ExitCode -eq 3 -and $run.State.Actions.Count -gt 0) { Show-ActionsPage $run.State }
    else { Show-SummaryPage $script:LastState $run.StderrText }
  }
}

function Update-RunView {
  param($State, $Event, [string]$Type)
  $step = [string]$Event.step
  switch ($Type) {
    'run_start' {
      $script:RunList.Items.Clear()
      foreach ($id in $State.Steps) {
        $script:RunRows[$id] = Add-ListItem $script:RunList @((Get-StationStepLabel $script:Texts $id), 'Na fila', '') $null $id
      }
      Add-Detail ('Log: {0}' -f $State.LogFile)
    }
    'step_start' {
      $label = Get-StationStepLabel $script:Texts $step
      $script:CurrentLabel.Text = 'Etapa {0} de {1}: {2}' -f $State.Index, $State.Total, $label
      if ($script:RunRows[$step]) { $script:RunRows[$step].SubItems[1].Text = 'Em andamento…'; $script:RunRows[$step].EnsureVisible() }
      $script:StepBar.Style = 'Marquee'
    }
    'progress' {
      if ($null -ne $State.Percent) {
        $script:StepBar.Style = 'Continuous'
        $script:StepBar.Value = [math]::Max(0, [math]::Min(100, [int]$State.Percent))
      }
      if ($script:RunRows[$step]) { $script:RunRows[$step].SubItems[2].Text = [string]$Event.message }
      if ($State.Percent -ge 35 -and -not $script:ProgressCaptured) { $script:ProgressCaptured = $true; Save-Capture 'instalacao-progresso' }
    }
    'log' { Add-Detail ('[{0}] {1}' -f $Event.status, $Event.message) }
    'action_required' {
      $action = $State.Blocking
      if ($action -and $action.Kind -eq 'browser_code') { Show-CodePanel $action }
      elseif ($script:RunRows[$step]) { $script:RunRows[$step].SubItems[2].Text = 'Depende de você: será tratado ao fim da execução.' }
    }
    'action_resolved' {
      $script:CodePanel.Visible = $false
      Add-Detail ('[{0}] {1}' -f $Event.status, $Event.message)
      $script:CurrentLabel.Text = [string]$Event.message
    }
    'step_end' {
      $info = Get-StationStatusInfo $script:Texts $Event.status
      if ($script:RunRows[$step]) {
        $script:RunRows[$step].SubItems[1].Text = $info.Label
        $script:RunRows[$step].SubItems[2].Text = [string]$Event.message
      }
      $script:StepBar.Style = 'Continuous'
      $script:StepBar.Value = 0
    }
    'run_end' { $script:CurrentLabel.Text = Get-StationExitMessage $script:Texts $State.ExitCode }
  }
  $script:OverallBar.Value = Get-StationOverallPercent $State
}

function Add-Detail {
  param([string]$Text)
  $script:DetailsBox.AppendText($Text + "`r`n")
}

function Show-CodePanel {
  param($Action)
  $script:CodeUrl = $Action.Url
  $script:CodeMessage.Text = $Action.Message + "`r`n" + $script:Texts.actions.'gh-login'.guide
  $script:CodeBox.Text = $Action.Code
  $script:CodeOpen.Visible = [bool]$Action.Url
  $script:CodeDeadline = $null
  if ($Action.TimeoutSeconds) { $script:CodeDeadline = (Get-Date).AddSeconds([int]$Action.TimeoutSeconds) }
  $script:CodePanel.Visible = $true
  $script:CurrentLabel.Text = 'Aguardando você concluir o login no navegador…'
  if ($Action.Url -and -not $Action.BrowserOpenedByTool) { Open-Url $Action.Url }
  Update-CodeCountdown
  $script:CodeCopy.Focus()
  Save-Capture 'login-codigo-de-dispositivo'
}

function Update-CodeCountdown {
  if (-not $script:CodeDeadline -or -not $script:CodePanel.Visible) { return }
  $left = $script:CodeDeadline - (Get-Date)
  if ($left.TotalSeconds -lt 0) { $left = [TimeSpan]::Zero }
  $script:CodeCountdown.Text = 'O código expira em {0:mm\:ss}. O instalador continua sozinho quando você autorizar.' -f $left
}

# --- pendências: assistente de ações e de autenticação --------------------------------------------

function Show-ActionsPage {
  param($State)
  Set-Header 4 'Falta pouco: algumas coisas dependem de você'
  $page = New-Page
  [void](Add-Text $page 'Resolva os itens abaixo e clique em “Verificar e continuar”. O instalador confere cada um de novo; o que já estiver feito não se repete.')
  $fields = New-Object System.Collections.ArrayList
  $script:ActionFields = $fields
  $script:ActionErrors = New-Object System.Windows.Forms.ErrorProvider
  $script:ActionErrors.BlinkStyle = 'NeverBlink'
  $number = 0
  foreach ($action in $State.Actions) {
    $number++
    $guide = Get-StationActionGuide $script:Texts @{ id = $action.Id; kind = $action.Kind }
    $box = New-Object System.Windows.Forms.GroupBox
    $box.Text = '{0}. {1}' -f $number, $guide.Title
    $box.Name = 'Pedido_' + $action.Id
    $box.AutoSize = $true
    $box.AutoSizeMode = 'GrowAndShrink'
    $inner = New-Object System.Windows.Forms.FlowLayoutPanel
    $inner.FlowDirection = 'TopDown'
    $inner.WrapContents = $false
    $inner.AutoSize = $true
    $inner.Dock = 'Fill'
    $inner.Padding = New-Object System.Windows.Forms.Padding(6)
    $box.Controls.Add($inner)
    $width = [math]::Max(500, $content.ClientSize.Width - 90)
    foreach ($text in @($guide.Guide, $action.Message)) {
      if (-not $text) { continue }
      $label = New-Object System.Windows.Forms.Label
      $label.AutoSize = $true
      $label.UseMnemonic = $false
      $label.MaximumSize = New-Object System.Drawing.Size($width, 0)
      $label.Text = $text
      $label.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, 6)
      if ($text -eq $action.Message) { $label.Font = $fontBold }
      $inner.Controls.Add($label)
    }
    switch ($action.Kind) {
      'input' { foreach ($answer in $action.Answers) { [void]$fields.Add((Add-AnswerField $inner $answer $action $width)) } }
      'confirm' { foreach ($answer in $action.Answers) { [void]$fields.Add((Add-AnswerField $inner $answer $action $width)) } }
      'run_in_terminal' {
        if ($action.Command) {
          $commandBox = New-Object System.Windows.Forms.TextBox
          $commandBox.ReadOnly = $true
          $commandBox.Font = $fontMono
          $commandBox.Width = [math]::Min($width, 520)
          $commandBox.Text = $action.Command
          $commandBox.Name = 'Comando_' + $action.Id
          $commandBox.AccessibleName = 'Comando a executar no terminal'
          $inner.Controls.Add($commandBox)
          $row = New-Object System.Windows.Forms.FlowLayoutPanel
          $row.AutoSize = $true
          $open = Add-Button $row 'Abrir o terminal com este comando' ('AbrirTerminal_' + $action.Id) { Open-Terminal ([string]$this.Tag) }
          $open.Tag = $action.Command
          $copy = Add-Button $row 'Copiar o comando' ('CopiarComando_' + $action.Id) { Set-ClipboardText ([string]$this.Tag) 'Comando' }
          $copy.Tag = $action.Command
          $inner.Controls.Add($row)
        }
      }
      default {
        if ($action.Url) {
          $link = New-Object System.Windows.Forms.LinkLabel
          $link.AutoSize = $true
          $link.Text = $action.Url
          $link.Name = 'Link_' + $action.Id
          $link.Tag = $action.Url
          $link.add_LinkClicked({ Open-Url ([string]$this.Tag) })
          $inner.Controls.Add($link)
        }
        if ($action.Command) { [void](Add-Text $inner $action.Command -Font $fontMono) }
      }
    }
    $page.Controls.Add($box)
    $box.Tag = 'fixed'
  }
  $script:StatusLabel = Add-Text $page '' -Name 'Aviso'

  Set-Buttons -Primary 'Verificar e continuar' -OnPrimary { Submit-Answers } -Secondary 'Deixar para depois' -OnSecondary {
    Show-SummaryPage $script:LastState $script:LastStderr
  } -Cancel 'Fechar'
  if ($fields.Count -gt 0) { $fields[0].Control.Focus() }
  Save-Capture 'pendencias'
}

function Submit-Answers {
  # Valida localmente, grava o arquivo de respostas e roda o motor de novo (contrato, seção 6).
  $answers = [ordered]@{}
  $firstInvalid = $null
  foreach ($field in $script:ActionFields) {
    $value = $null
    if ($field.Control -is [System.Windows.Forms.CheckBox]) { $value = $field.Control.Checked }
    else { $value = $field.Control.Text }
    $valid = Test-StationAnswerValue $field.Type $value $field.Required
    if (-not $valid) {
      $message = 'Preencha este campo.'
      if ($field.Type -eq 'email' -and $value) { $message = 'Este e-mail não parece válido.' }
      $script:ActionErrors.SetError($field.Control, $message)
      $field.Control.AccessibleDescription = $message
      if (-not $firstInvalid) { $firstInvalid = $field.Control }
      continue
    }
    $script:ActionErrors.SetError($field.Control, '')
    $field.Control.AccessibleDescription = ''
    if ($field.Type -eq 'boolean' -or -not [string]::IsNullOrWhiteSpace([string]$value)) { $answers[$field.Key] = $value }
  }
  if ($firstInvalid) {
    $script:StatusLabel.Text = 'Há campos a corrigir: veja os itens marcados.'
    $firstInvalid.Focus(); return
  }
  $file = $null
  if ($answers.Count -gt 0) { $file = New-StationAnswersFile -Answers $answers }
  Show-RunPage -AnswersFile $file
}

function Add-AnswerField {
  # Campo de resposta pelo tipo do contrato. Não há tipo de senha: o contrato não pede credencial.
  param($Parent, $Answer, $Action, [int]$Width)
  $key = [string]$Answer.key
  $type = [string]$Answer.type
  $default = Get-StationProperty $Answer 'default'
  if ($type -eq 'boolean') {
    $check = New-Object System.Windows.Forms.CheckBox
    $check.AutoSize = $true
    $check.Text = $Answer.label
    $check.Name = 'Resposta_' + $key
    $check.Checked = ($default -eq $true)
    $Parent.Controls.Add($check)
    return [pscustomobject]@{ Key = $key; Type = $type; Required = $false; Control = $check }
  }
  $label = New-Object System.Windows.Forms.Label
  $label.AutoSize = $true
  $label.Text = '&' + $Answer.label
  $label.Margin = New-Object System.Windows.Forms.Padding(0, 4, 0, 0)
  $box = New-Object System.Windows.Forms.TextBox
  $box.Name = 'Resposta_' + $key
  $box.AccessibleName = $Answer.label
  $box.Width = [math]::Min($Width, 420)
  if ($null -ne $default) { $box.Text = [string]$default }
  $Parent.Controls.Add($label)
  $Parent.Controls.Add($box)
  return [pscustomobject]@{ Key = $key; Type = $type; Required = [bool]$Answer.required; Control = $box }
}

# --- passo 5: resumo ------------------------------------------------------------------------------

function Show-SummaryPage {
  param($State, [string]$Stderr)
  Set-Header 5 'Resumo'
  $page = New-Page
  $code = [int]$State.ExitCode
  [void](Add-Text $page (Get-StationExitMessage $script:Texts $code) -Font $fontBold -Name 'Conclusao')
  $eventWarning = Get-StationEventWarning $script:Texts $State
  if ($eventWarning) { [void](Add-Text $page $eventWarning -Name 'AvisoDeEventosAusentes') }
  $list = New-ListView $page 'ListaResumo' 'Resumo por etapa' @(@('Etapa', 260), @('Situação', 200), @('Detalhe', 320)) 280
  $summary = Get-StationSummary $script:Texts $State
  foreach ($groupName in $summary.Keys) {
    $items = @($summary[$groupName])
    if ($items.Count -eq 0) { continue }
    $group = New-Object System.Windows.Forms.ListViewGroup(('{0} ({1})' -f $script:Texts.groups.$groupName, $items.Count))
    [void]$list.Groups.Add($group)
    foreach ($item in $items) { [void](Add-ListItem $list @($item.Label, $item.Status, $item.Message) $group $item.Step) }
  }
  $failures = @($summary.failed)
  if ($failures.Count -gt 0 -or $code -in 2, 130) {
    $details = New-Object System.Collections.ArrayList
    foreach ($item in $failures) {
      [void]$details.Add(('{0}: {1}' -f $item.Label, $item.Message))
      $output = Get-StationProperty $State.StepData[$item.Step] 'output'
      if ($output) { [void]$details.Add($output) }
    }
    foreach ($log in @($State.Logs | Where-Object { $_.Level -eq 'error' })) { [void]$details.Add($log.Message) }
    if ($Stderr) { [void]$details.Add('Saída de erro do instalador:'); [void]$details.Add($Stderr.Trim()) }
    if ($details.Count -gt 0) {
      [void](Add-Text $page 'O que deu errado' -Font $fontBold -SpaceAfter 2)
      $box = New-Object System.Windows.Forms.TextBox
      $box.Name = 'DetalhesDaFalha'
      $box.AccessibleName = 'Detalhes da falha'
      $box.Multiline = $true; $box.ReadOnly = $true; $box.ScrollBars = 'Vertical'; $box.Font = $fontMono
      $box.Height = 90
      $box.Text = ($details -join "`r`n")
      $page.Controls.Add($box)
    }
  }
  if ($State.LogFile) {
    [void](Add-Text $page 'Log desta execução' -Font $fontBold -SpaceAfter 2)
    $logBox = New-Object System.Windows.Forms.TextBox
    $logBox.Name = 'CaminhoDoLog'
    $logBox.AccessibleName = 'Caminho do log desta execução'
    $logBox.ReadOnly = $true
    $logBox.Text = $State.LogFile
    $page.Controls.Add($logBox)
    $row = Add-Row $page
    $row.Tag = 'fixed'
    $openLog = Add-Button $row 'Abrir a pasta do log' 'AbrirPastaDoLog' {
      Start-Process -FilePath 'explorer.exe' -ArgumentList ('/select,' + (ConvertTo-StationArgument ([string]$this.Tag)))
    }
    $openLog.Tag = $State.LogFile
    $copyLog = Add-Button $row 'Copiar o caminho do log' 'CopiarCaminhoDoLog' { Set-ClipboardText ([string]$this.Tag) 'Caminho do log' }
    $copyLog.Tag = $State.LogFile
    if ($State.Actions.Count -gt 0) {
      [void](Add-Button $row 'Resolver as pendências' 'ResolverPendencias' { Show-ActionsPage $script:LastState })
    }
  }
  $script:StatusLabel = Add-Text $page '' -Name 'Aviso'
  [void](Add-Text $page 'Rodar de novo é seguro: o instalador só faz o que faltar, e o que já estiver pronto aparece como “Já estava”.')
  Set-Buttons -Primary 'Concluir' -OnPrimary { $form.Close() } -Secondary 'Rodar de novo' -OnSecondary { Show-RunPage -NewSession } -Cancel $null
  $list.Focus()
  Save-Capture ('resumo-codigo-{0}' -f $code)
}

# --- ciclo de vida --------------------------------------------------------------------------------

$form.add_FormClosing({
    param($sender, $eventArgs)
    if ($script:Run) {
      $answer = [System.Windows.Forms.MessageBox]::Show($form,
        'O instalador ainda está rodando. Interromper agora? Nada fica pela metade: a próxima execução recomeça a etapa.',
        $script:Texts.product, 'YesNo', 'Question')
      if ($answer -ne 'Yes') { $eventArgs.Cancel = $true; return }
      $script:Closing = $true
      Stop-EngineRun
    }
  })

$form.add_KeyDown({
    param($sender, $eventArgs)
    if ($eventArgs.KeyCode -eq 'Escape') {
      $eventArgs.Handled = $true
      if ($script:Run) { Invoke-Interrupt } elseif ($btnCancel.Visible) { $form.Close() }
    }
  })

function Invoke-Interrupt {
  $answer = [System.Windows.Forms.MessageBox]::Show($form,
    'Interromper o instalador? Nada fica pela metade: a próxima execução recomeça a etapa.',
    $script:Texts.product, 'YesNo', 'Question')
  if ($answer -eq 'Yes') { Stop-EngineRun }
}

$btnCancel.add_Click({ if ($script:Run) { Invoke-Interrupt } else { $form.Close() } })

$form.add_Shown({
    if (-not (Test-Path -LiteralPath $script:EnginePath)) {
      [void][System.Windows.Forms.MessageBox]::Show($form,
        "O motor do instalador não foi encontrado em:`r`n$($script:EnginePath)`r`n`r`nBaixe o pacote completo do instalador e tente de novo.",
        $script:Texts.product, 'OK', 'Error')
      $form.Close(); return
    }
    Show-WelcomePage
  })

try {
  [System.Windows.Forms.Application]::Run($form)
}
catch {
  [void][System.Windows.Forms.MessageBox]::Show("Erro inesperado no assistente:`r`n`r`n$($_.Exception.Message)",
    'Instalador da estação HubICG', 'OK', 'Error')
  exit 1
}
finally {
  Stop-EngineRun
  $timer.Dispose()
}
