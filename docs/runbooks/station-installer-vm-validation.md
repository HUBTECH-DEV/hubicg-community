> Procedimento de aceite em VM; a presença deste roteiro não comprova execução real.
> Gere antes o export público com python scripts/build_station_agents.py no checkout Community.

# Roteiro de validação do instalador da estação em VM limpa

Community #146. Critério de aceite: execução real em VM limpa de cada sistema disponível, **duas vezes**, com a
saída das duas anexada ao PR.

Este roteiro cobre o aceite Windows e Linux. O motor macOS permanece experimental.

---

## 1. Antes de começar

### 1.1 O que a validação prova

| Pergunta | Como se prova |
|---|---|
| O instalador funciona numa máquina sem nada? | 1ª execução termina com código 0 (ou 3 só por login pendente) e as ferramentas existem no fim. |
| Ele é idempotente? | 2ª execução: toda etapa `already`, `checked`, `unsupported` ou `skipped`, código 0. |
| Ele não toca em credencial? | O log não tem token; o login é feito pela pessoa no navegador. |
| O check só verifica? | `-Check` antes da instalação não cria nada. |

### 1.2 O que preparar

- Uma conta GitHub **de teste** com acesso de leitura a `HUBTECH-DEV/hubicg-community`, e uma conta
  Claude para o login. Não use a conta pessoal se a VM for compartilhada.
- A pasta do instalador da branch `feat/146-station-windows-linux`, copiada do host para a VM (pasta
  compartilhada, `scp` ou pendrive): `installers/station/` e `.hubicg/exports/station-agents/`. A VM limpa
  não tem git para clonar a branch, e o clone que o instalador faz traz a `main`, que ainda não tem os
  agentes. Por isso, até o merge, a etapa de agentes usa a cópia (`-AgentsSource` / `--agents-source`).
- Rede: se a VM sair pela rede corporativa (Netskope), anote. O roteiro serve com e sem inspeção TLS, e o
  resultado muda: com inspeção, a etapa `git` do Windows pede autorização para `schannel`.

### 1.3 Snapshot

Tire um **snapshot da VM limpa** antes da primeira execução. Ele permite repetir do zero sem reinstalar o
sistema.

---

## 2. Windows (10 ou 11, x64)

### 2.1 VM

- Windows 11 (ou 10 22H2) recém-instalado, usuário local **sem** privilégio de administrador e um usuário
  administrador separado (o winget pede elevação para o Git; o UAC aparece).
- **Não** instale Git, GitHub CLI, Python ou Claude antes.
- Confirme que o `winget` existe: `winget --version`. Num Windows recém-instalado, o App Installer pode
  ainda estar se atualizando; espere a Microsoft Store concluir. Se faltar, o instalador pede a ação
  `package-manager-missing` (isso também é um resultado válido para anotar).

### 2.2 Execução

No PowerShell (Windows PowerShell 5.1, não o 7), na pasta copiada:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
$saida = "$env:USERPROFILE\Desktop\hubicg-vm"
New-Item -ItemType Directory -Force $saida | Out-Null

# 0. Ambiente e verificação, antes de instalar
.\installers\station\hubicg-station.ps1 -Check -Json -NonInteractive -AgentsSource .\.hubicg\exports\station-agents |
    Out-File -Encoding utf8 "$saida\00-check.jsonl"
"exit=$LASTEXITCODE" | Out-File -Append -Encoding utf8 "$saida\00-check.jsonl"

# 1. Primeira execução, interativa (os logins abrem no navegador)
.\installers\station\hubicg-station.ps1 -AgentsSource .\.hubicg\exports\station-agents *>&1 |
    Tee-Object "$saida\01-primeira.txt"
"exit=$LASTEXITCODE" | Out-File -Append -Encoding utf8 "$saida\01-primeira.txt"
```

Durante a primeira execução, responda ao que for pedido: nome e e-mail do git, login do GitHub no
navegador, login do Claude Code, login no Claude Desktop (o instalador abre o app e pergunta se
concluiu).

Feche o PowerShell, abra outro (para o `PATH` novo valer) e rode a segunda vez, nos dois modos:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
$saida = "$env:USERPROFILE\Desktop\hubicg-vm"
.\installers\station\hubicg-station.ps1 -AgentsSource .\.hubicg\exports\station-agents *>&1 |
    Tee-Object "$saida\02-segunda.txt"
"exit=$LASTEXITCODE" | Out-File -Append -Encoding utf8 "$saida\02-segunda.txt"

.\installers\station\hubicg-station.ps1 -Json -NonInteractive -AgentsSource .\.hubicg\exports\station-agents |
    Out-File -Encoding utf8 "$saida\03-segunda-json.jsonl"
"exit=$LASTEXITCODE" | Out-File -Append -Encoding utf8 "$saida\03-segunda-json.jsonl"
```

### 2.3 O que conferir

- `02-segunda.txt`: toda linha de etapa com `already`, `checked` ou `skipped`; última linha
  `Concluido: nada pendente.` e `exit=0`.
- `claude --version`, `gh auth status`, `git config --global --get user.name` num terminal novo.
- `%USERPROFILE%\.claude\agents` com um arquivo por role, e `%USERPROFILE%\.claude\.hubicg-station.json`.
- O Claude Desktop abre e está logado.

### 2.4 O que coletar

- A pasta `Desktop\hubicg-vm` inteira.
- Os logs em `%LOCALAPPDATA%\HubICG\station\logs`.
- Versão do Windows (`winver`) e se a rede tinha inspeção TLS.

---

## 3. Linux

Rode em **duas** distribuições, uma de cada família de pacotes:

| Família | Sugestão de VM | Observação |
|---|---|---|
| apt | Ubuntu 24.04 LTS Desktop | configura o repositório apt oficial do GitHub CLI |
| dnf | Fedora 41+ ou Rocky Linux 10 | `gh` vem do repositório da distribuição |

### 3.1 VM

- Instalação limpa, com um usuário comum que tem `sudo` (o padrão do Ubuntu e do Fedora). Não rode como
  root: o caminho com `sudo` é o que se quer validar.
- **Não** instale git, gh, curl ou Claude antes. No Ubuntu Desktop o `curl` não vem instalado; o
  instalador o instala.
- O instalador precisa do `bash` (já presente) e de `sudo` com senha: ele mesmo não lê a senha; o `sudo`
  pergunta no terminal.

### 3.2 Execução

Na pasta copiada:

```sh
saida="$HOME/hubicg-vm"; mkdir -p "$saida"

# 0. Verificação antes de instalar
bash installers/station/hubicg-station.sh --check --json --non-interactive \
  --agents-source .hubicg/exports/station-agents > "$saida/00-check.jsonl"; echo "exit=$?" >> "$saida/00-check.jsonl"

# 1. Primeira execução, interativa
bash installers/station/hubicg-station.sh --agents-source .hubicg/exports/station-agents 2>&1 | tee "$saida/01-primeira.txt"
echo "exit=${PIPESTATUS[0]}" >> "$saida/01-primeira.txt"
```

Responda ao que for pedido: senha do `sudo` (para o próprio `sudo`), nome e e-mail do git, login do
GitHub (o gh mostra um código e abre o navegador), inclusão de `~/.local/bin` no `PATH`, login do
Claude Code.

Abra um terminal novo e rode a segunda vez:

```sh
saida="$HOME/hubicg-vm"
bash installers/station/hubicg-station.sh --agents-source .hubicg/exports/station-agents 2>&1 | tee "$saida/02-segunda.txt"
echo "exit=${PIPESTATUS[0]}" >> "$saida/02-segunda.txt"
bash installers/station/hubicg-station.sh --json --non-interactive \
  --agents-source .hubicg/exports/station-agents > "$saida/03-segunda-json.jsonl"; echo "exit=$?" >> "$saida/03-segunda-json.jsonl"
```

### 3.3 O que conferir

- `02-segunda.txt`: toda etapa `already`, `checked`, `unsupported` (Claude Desktop) ou `skipped`; `exit=0`.
- `claude --version`, `gh auth status` e `git config --global --get user.name` num terminal novo.
- `~/.claude/agents` com um arquivo por role, e `~/.claude/.hubicg-station.json`.
- No Ubuntu: `/etc/apt/sources.list.d/github-cli.list` e `/etc/apt/keyrings/githubcli-archive-keyring.gpg`.

### 3.4 O que coletar

- A pasta `~/hubicg-vm` inteira e os logs de `~/.local/state/hubicg/station/logs`.
- `cat /etc/os-release`, `uname -m` e se a rede tinha inspeção TLS.

---

## 4. Variações que valem a pena (opcionais)

| Cenário | Como provocar | Resultado esperado |
|---|---|---|
| Interface gráfica (modo motor) | rodar a 1ª execução com `-Json -NonInteractive` / `--json --non-interactive` | Código 3 com pedidos `git-identity`, `gh-login` (`browser_code`, com código), `claude-login`; depois de resolver, código 0. |
| Conta sem acesso ao repositório | logar no gh com uma conta sem acesso | pedido `repo-access`, `repo` e `agents` em `blocked`, código 3. |
| Agente seu | criar `~/.claude/agents/principal-devops-engineer.md` antes | conflito reportado, arquivo intacto. |
| Clone com alteração | editar um arquivo do clone e rodar de novo | `repo` em `already`, aviso, nada descartado. |

---

## 5. Como devolver

Compacte as pastas coletadas por sistema (`windows.zip`, `ubuntu.zip`, `fedora.zip`) e anexe ao PR da
#146, com uma linha por sistema: versão, rede (com ou sem inspeção TLS), código de saída da 1ª e da 2ª
execução. Onde não houver VM, registre "não verificado".

## macOS experimental

O motor shell mantém o suporte experimental. Não há aceite integral nem GUI macOS neste recorte.
