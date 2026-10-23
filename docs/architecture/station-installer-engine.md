# Contrato do motor do instalador da estação HubICG

Data: 22/10/2026
Status: **versão 1 do contrato** (`hubicg.station.event/1`). Community #146: motores e interfaces Windows/Linux.
Esquema dos eventos: [`docs/schemas/station-event.schema.json`](../schemas/station-event.schema.json).

Este documento define a fronteira entre o **motor** do instalador e qualquer **interface** que o conduza. O
motor verifica, instala e configura; a interface só mostra o que o motor emite e devolve as respostas do
usuário. Nenhuma lógica de instalação mora na interface.

Há dois motores com o mesmo contrato:

| Sistema | Motor | Interface Windows/Linux |
|---|---|---|
| Windows | `installers/station/hubicg-station.ps1` (Windows PowerShell 5.1) | W1, WinForms |
| Linux | `installers/station/hubicg-station.sh` (bash) | L1, zenity |
| macOS (experimental) | `installers/station/hubicg-station.sh` (bash 3.2) | fora deste recorte; sem GUI |

O contrato não depende do sistema. Onde um sistema se comporta diferente, a diferença aparece como **dado**
(por exemplo, `status: "unsupported"`), nunca como formato diferente de evento.

---

## 1. Princípios

1. **Idempotência é o mecanismo de retomada.** Rodar de novo nunca desfaz nem repete o que já foi feito. Por
   isso a interface não precisa guardar estado: depois de qualquer ação do usuário, ela roda o motor de novo.
2. **Uma conversa por execução, em mão única.** O motor fala por `stdout`; a interface responde **na próxima
   execução**, por parâmetros ou por um arquivo de respostas. O motor nunca lê respostas de `stdin` em modo
   não interativo. Esse desenho serve às três interfaces, inclusive às que não conseguem escrever no `stdin` de
   um processo em execução (AppleScript, zenity).
3. **Credenciais nunca passam pelo motor.** Ele não pede, não lê, não exibe e não grava token, senha, cookie ou
   código de recuperação. Login é sempre o fluxo oficial da ferramenta (`gh auth login`, `claude auth login`, o
   próprio app). O único código que o motor pode repassar é o **código de dispositivo** de uso único que a
   ferramenta oficial mostra para ser digitado no navegador (seção 5.3).
4. **Nada é sobrescrito sem ser do instalador.** Arquivo que o instalador não criou, ou que foi alterado depois
   que ele criou, é mantido e reportado como conflito.
5. **A verificação TLS nunca é desligada.** Com inspeção TLS corporativa (Netskope e afins), o motor explica o
   que configurar e onde, e não contorna.

---

## 2. Invocação

Os nomes são os mesmos nos dois motores; muda só a grafia do parâmetro.

| Opção | PowerShell | bash | Efeito |
|---|---|---|---|
| Modo verificação | `-Check` | `--check` | Só verifica. Nada é instalado nem configurado. |
| Modo simulação | `-WhatIf` | `--dry-run` | Mostra o que faria, com os comandos. Nada é alterado. |
| Modo aplicação | (padrão) | (padrão) | Instala e configura. |
| Eventos JSON | `-Json` | `--json` | Um evento JSON por linha em `stdout` (seção 3). |
| Não interativo | `-NonInteractive` | `--non-interactive` | Nunca pergunta no terminal. Toda pendência vira `action_required`. **A interface sempre usa esta opção.** |
| Etapas | `-Only git,gh` | `--only git,gh` | Roda só as etapas listadas. `environment` sempre roda. |
| Arquivo de respostas | `-AnswersFile <arq>` | `--answers-file <arq>` | Respostas da interface (seção 6). |
| Diretório do clone | `-RepoDir <dir>` | `--repo-dir <dir>` | Padrão: `~/github/hubicg-community`. |
| Configuração do Claude | `-ConfigDir <dir>` | `--config-dir <dir>` | Padrão: `CLAUDE_CONFIG_DIR`, senão `~/.claude`. |
| Origem dos agentes | `-AgentsSource <dir>` | `--agents-source <dir>` | Padrão: `<repoDir>/.hubicg/exports/station-agents`. Útil para validar uma branch antes do merge. |
| Repositório | `-Repository <dono/nome>` | `--repository <dono/nome>` | Padrão: `HUBTECH-DEV/hubicg-community`. |
| Sem rede | `-SkipNetwork` | `--skip-network` | Pula os testes de conectividade e TLS (testes automatizados). |

### Export público dos agentes

Antes da aplicação, execute `python scripts/build_station_agents.py` no clone
Community (no Linux, `python3`). O export valida o manifest público, reutiliza
o adaptador Claude Code e expande as foundations das roles. A saída padrão é
`.hubicg/exports/station-agents/`; `--output` permite um diretório novo.
O gerador não substitui arquivos divergentes nem elimina arquivos adicionais.
O recibo `.hubicg-station-export.json` fixa o SHA-256 do manifest da biblioteca.
No caminho padrão, os motores comparam esse recibo com o manifest do clone
selecionado, inclusive após atualização do clone. Export antigo ou sem recibo
gera `agents-export-stale` / `action_required`, sem alterar agentes instalados.
Preserve a pasta antiga com outro nome e gere um export novo no caminho padrão.
Um `AgentsSource` explícito é um artefato externo: valida-se seu corpo, sem
afirmar atualidade em relação à biblioteca do clone (`sourceMode: external`).
Se o export faltar, a aplicação emite `agents-export`, kind `external`, e termina
a etapa com `action_required`. Gere o artefato e repita a execução. Não há
dependência de configuração ou biblioteca privada.

No transporte da estação, o hash do marcador cobre os bytes UTF-8 do corpo
após o frontmatter, incluindo foundations. Ele detecta corrupção/edição e
difere do hash nome/instruções do adaptador CLI, que permanece inalterado.
Use apenas exports externos de origem confiável: um hash não autentica o autor.
| Arquivo de log | `-LogFile <arq>` | `--log-file <arq>` | Substitui o caminho padrão do log (seção 8). |
| Versão do contrato | `-ContractVersion` | `--contract-version` | Imprime `hubicg.station.event/1` e sai com 0. |

`-Check` e `-WhatIf` juntos valem como `-Check`. Opção desconhecida termina com código 2 antes de qualquer etapa.

Sem `-Json`, o motor escreve texto legível para pessoas. **Esse texto não é contrato** e pode mudar a qualquer
momento; interface nenhuma deve interpretá-lo.

---

## 3. Eventos

Com `-Json`/`--json`, `stdout` contém **somente** eventos, um objeto JSON por linha, em UTF-8, terminado por
`\n`. Qualquer outra saída (de ferramentas chamadas pelo motor, por exemplo) vai para `stderr`, que a interface
pode anexar ao relatório de erro, mas não deve interpretar.

### 3.1 Envelope

Todo evento tem os mesmos campos:

```json
{
  "schema": "hubicg.station.event/1",
  "runId": "20261022T143005Z-4f1c",
  "seq": 7,
  "ts": "2026-10-22T14:30:09Z",
  "type": "step_end",
  "step": "git",
  "status": "already",
  "message": "git 2.47.1 já estava instalado",
  "data": { "version": "2.47.1" }
}
```

| Campo | Tipo | Regra |
|---|---|---|
| `schema` | string | Sempre `hubicg.station.event/1` nesta versão. |
| `runId` | string | Identifica a execução. Igual em todos os eventos de uma execução. |
| `seq` | inteiro | Começa em 1 e cresce de 1 em 1. Lacuna indica evento perdido. |
| `ts` | string | UTC, RFC 3339, precisão de segundos. |
| `type` | string | Um dos tipos da seção 3.2. |
| `step` | string | Id da etapa (seção 4). Vazio em `run_start` e `run_end`. |
| `status` | string | Depende do tipo (seção 3.3). Vazio quando o tipo não usa. |
| `message` | string | Texto em pt-BR para mostrar ao usuário como está. |
| `data` | objeto | Dados estruturados do tipo. Sempre presente, mesmo vazio. |

A interface deve **ignorar campos que não conhece** em `data` e no envelope. Isso é o que permite evolução
compatível (seção 9).

### 3.2 Tipos

Uma execução sempre segue esta gramática:

```text
run_start
  ( step_start  (progress | log | action_required | action_resolved)*  step_end )*
run_end
```

| Tipo | Quando | `data` |
|---|---|---|
| `run_start` | Primeiro evento. | `engine` (versão do motor), `contract` (`1`), `mode` (`check`, `plan`, `apply`), `os` (`windows`, `linux`, `macos`), `interactive`, `steps` (lista em ordem), `repoDir`, `configDir`, `logFile`. |
| `step_start` | Início de uma etapa. | `index` (1..n), `total` (n). A interface calcula o progresso geral com eles. |
| `progress` | Andamento dentro de uma etapa longa (download, clone). | Opcional: `percent` (0..100), `bytes`, `totalBytes`. Sem `percent`, a interface mostra progresso indeterminado. |
| `log` | Informação, aviso ou erro que não encerra a etapa. `status` é `info`, `warn` ou `error`. | Opcional: `command`, `output` (já sanitizado, seção 8). |
| `action_required` | O motor precisa de algo do usuário (seção 5). | Ver seção 5. |
| `action_resolved` | Fim de uma ação de espera (`browser_code`). `status` é `completed`, `timeout` ou `failed`. | `id` da ação. |
| `step_end` | Fim de uma etapa. `status` é o resultado (seção 3.3). | Dados da etapa (seção 4). |
| `run_end` | Último evento. | `exitCode` e `steps` (mapa etapa → status). |

Se o processo terminar sem `run_end`, a execução foi interrompida (por exemplo, a interface encerrou o processo).
A interface trata como código 130.

### 3.3 Status de `step_end`

| Status | Significado | Conta como |
|---|---|---|
| `checked` | Só da etapa `environment`: verificação feita. | ok |
| `already` | Já estava como deveria; nada foi feito. | ok |
| `installed` | Instalado nesta execução. | ok |
| `updated` | Atualizado nesta execução. | ok |
| `configured` | Configurado nesta execução. | ok |
| `unsupported` | Não existe para este sistema; registrado sem falhar. | ok |
| `skipped` | Fora da seleção de `-Only`, ou não se aplica. | ok |
| `missing` | Modo verificação: falta instalar ou configurar. | pendente |
| `would_install`, `would_configure`, `would_update` | Modo simulação: o que seria feito. `data.command` traz o comando quando houver. | pendente |
| `action_required` | Parou esperando o usuário. Veio antes um `action_required`. | ação |
| `blocked` | Não rodou porque uma dependência terminou em `failed`, `action_required` ou `blocked`. `data.blockedBy` lista quais. | ação |
| `failed` | Erro. `message` explica; `data.output` pode trazer a saída sanitizada. | falha |

Na segunda execução seguida em modo aplicação, sem mudança externa, **toda etapa termina em `already`,
`checked`, `unsupported` ou `skipped`**. Esse é o critério de idempotência testado.

---

## 4. Etapas

Ordem fixa. A interface não deve assumir a quantidade: ela vem em `run_start.data.steps`.

| Id | Depende de | Faz | Windows | Linux | macOS |
|---|---|---|---|---|---|
| `environment` | — | Verificação de ambiente (4.1). Nunca altera nada. | sim | sim | sim |
| `git` | — | Instala o Git se faltar. Com inspeção TLS no Windows, oferece `http.sslBackend=schannel`. | winget | apt / dnf | (a definir) |
| `git-identity` | `git` | Configura `user.name` e `user.email` **só se vazios**. | sim | sim | sim |
| `gh` | — | Instala o GitHub CLI se faltar. | winget | apt / dnf (repositório oficial) | (a definir) |
| `gh-auth` | `gh` | Sessão do gh (login oficial), `gh auth setup-git` e acesso a `HUBTECH-DEV/hubicg-community`. | sim | sim | sim |
| `repo` | `git`, `gh-auth` | Clona, ou faz `fetch` e `pull --ff-only`. Nunca descarta alteração local. | sim | sim | sim |
| `claude-cli` | — | Instala o Claude Code CLI pelo instalador oficial e garante o `PATH`. | sim | sim | (a definir) |
| `claude-cli-auth` | `claude-cli` | Sessão do Claude Code (`claude auth status`, `claude auth login`). | sim | sim | sim |
| `claude-desktop` | — | Instala o Claude Desktop. | sim | `unsupported` | (a definir) |
| `claude-desktop-auth` | `claude-desktop` | Abre o app e pede a confirmação do login ao usuário. | sim | `unsupported` | sim |
| `agents` | `repo` | Instala os agentes HubICG em `<configDir>/agents`, com manifesto. | sim | sim | sim |

Em modo verificação e simulação, `blocked` não é usado: cada etapa reporta o próprio estado.

### 4.1 `environment` — dados

`step_end.data` traz o relatório de ambiente. Campos garantidos (valor `null` quando não se aplica ou não foi
possível medir):

| Campo | Exemplo |
|---|---|
| `os`, `osVersion`, `arch` | `"windows"`, `"10.0.26300"`, `"AMD64"` |
| `shell`, `shellVersion` | `"powershell"`, `"5.1.26100.1"` |
| `admin` | `false` (Windows: administrador; Linux/macOS: `root`) |
| `sudo` | `"passwordless"`, `"password"`, `"absent"` ou `null` no Windows |
| `packageManager` | `"winget"`, `"apt"`, `"dnf"`, `"brew"` ou `null` |
| `diskFreeGB` | `120.4` (no volume do `repoDir`) |
| `proxy` | `{ "HTTPS_PROXY": "http://***@proxy:8080" }`: só presença e host; credencial da URL é mascarada |
| `tools` | `{ "git": "2.47.1", "gh": null, "claude": "2.1.300", ... }`: `null` = ausente |
| `network` | por host: `{ "verdict": "direct", "issuer": "...", "trusted": true }`, ou `"skipped"` |
| `tls` | `"direct"`, `"inspected"`, `"suspected"`, `"unreachable"` ou `"skipped"` |

Hosts testados: `github.com`, `api.github.com`, `claude.ai`, `api.anthropic.com`, `downloads.claude.ai`.

`tls` vale `inspected` quando o emissor do certificado é de um fornecedor conhecido de inspeção (Netskope,
Zscaler e afins), e `suspected` quando o emissor não é uma CA pública conhecida. Nos dois casos o motor emite um
`log` de aviso explicando, por ferramenta, o que configurar (repositório de certificados do sistema,
`http.sslBackend`, `NODE_EXTRA_CA_CERTS`), sem desligar a verificação.

### 4.2 `agents` — dados

```json
{ "target": "C:/Users/x/.claude/agents", "source": ".../.hubicg/exports/station-agents", "total": 65,
  "counts": { "installed": 0, "updated": 0, "already": 65, "removed": 0, "conflict": 0 },
  "conflicts": [] }
```

O manifesto fica em `<configDir>/.hubicg-station.json` e registra o hash de cada agente instalado. Regras:

- igual ao da origem: `already`;
- diferente e registrado no manifesto com o mesmo hash do disco: atualizado;
- diferente e fora do manifesto, ou alterado depois da instalação: **conflito, mantido**;
- registrado no manifesto, saiu da biblioteca e não foi alterado: removido.

Conflito não é falha: aparece em `data.conflicts` e num `log` de aviso por arquivo.

---

## 5. Pedidos de ação do usuário

Quando o motor precisa de algo que só a pessoa pode fazer, ele emite `action_required`. O `data` é:

| Campo | Tipo | Regra |
|---|---|---|
| `id` | string | Id estável do pedido (catálogo na seção 5.5). A interface pode escolher o diálogo por ele. |
| `kind` | string | `input`, `confirm`, `browser_code`, `run_in_terminal` ou `external` (5.1 a 5.4). |
| `blocking` | booleano | `true` só em `browser_code`: o motor está **esperando** e segue sozinho. Nos demais é `false`: a etapa termina em `action_required` e o motor segue para as etapas independentes. |
| `answers` | lista | Só em `input` e `confirm`: as chaves que a interface deve responder (seção 6). |
| `command` | string | Comando oficial que resolve, quando houver. |
| `url` | string | Endereço a abrir, quando houver. |
| `code` | string | Só em `browser_code`: o código de dispositivo de uso único. |
| `timeoutSeconds` | inteiro | Só em `browser_code`: quanto o motor espera. |

O texto para mostrar está em `message`, já em pt-BR.

### 5.1 `input` e `confirm`

O motor precisa de um valor (`input`) ou de um sim/não (`confirm`). A etapa termina em `action_required` e o
motor segue com as etapas que não dependem dela. A interface coleta a resposta, grava o arquivo de respostas e
roda o motor de novo (seção 6).

```json
{"type":"action_required","step":"git-identity","status":"action_required",
 "message":"Informe o nome e o e-mail que vão assinar os commits.",
 "data":{"id":"git-identity","kind":"input","blocking":false,
  "answers":[
   {"key":"git.name","type":"string","label":"Nome","required":true},
   {"key":"git.email","type":"email","label":"E-mail","required":true}]}}
```

Cada item de `answers` tem `key`, `type` (`string`, `email` ou `boolean`), `label` (pt-BR), `required` e,
opcionalmente, `default`.

### 5.2 `run_in_terminal`

O fluxo oficial exige um terminal (por exemplo, `claude auth login`, que pode pedir para colar no terminal um
código vindo do navegador). A interface abre um terminal com `command`, ou instrui a pessoa a abrir, e roda o
motor de novo quando ela disser que terminou. O motor verifica o resultado na execução seguinte.

### 5.3 `browser_code` — "abra o navegador e digite o código X"

Para fluxos de dispositivo (o `gh auth login --web`, por exemplo), o motor roda o fluxo oficial, captura o código
de uso único que a ferramenta mostra e emite:

```json
{"type":"action_required","step":"gh-auth","status":"action_required",
 "message":"Abra https://github.com/login/device e digite o código ABCD-1234.",
 "data":{"id":"gh-login","kind":"browser_code","blocking":true,
  "url":"https://github.com/login/device","code":"ABCD-1234","timeoutSeconds":900,
  "browserOpenedByTool":false}}
```

- O motor **continua rodando** e esperando a ferramenta.
- A interface mostra o código em destaque, oferece copiar e abre `url` no navegador, a menos que
  `browserOpenedByTool` seja `true`.
- Quando o fluxo termina, o motor emite `action_resolved` com `status` `completed`, `timeout` ou `failed`, e só
  depois o `step_end` da etapa.
- Para cancelar, a interface encerra o processo do motor. Nada fica pela metade: a próxima execução recomeça a
  etapa.

O código de dispositivo é de uso único, expira em minutos e só autoriza o que a pessoa aprovar no navegador. Ele
não é credencial e não é gravado no log (seção 8).

### 5.4 `external`

Algo fora da máquina: pedir acesso ao repositório a um owner da organização, instalar o App Installer da
Microsoft Store, liberar um host no proxy. A interface mostra `message` (e `url`, se houver) e oferece "verificar
de novo", que roda o motor outra vez.

### 5.5 Catálogo de pedidos

| `id` | Etapa | `kind` | Resolve com |
|---|---|---|---|
| `git-identity` | `git-identity` | `input` | `git.name`, `git.email` |
| `git-system-cert-store` | `git` | `confirm` | `git.useSystemCertStore` (Windows com inspeção TLS) |
| `gh-login` | `gh-auth` | `browser_code` ou `run_in_terminal` | fluxo oficial do gh |
| `repo-access` | `gh-auth` | `external` | acesso concedido por um owner de `HUBTECH-DEV` |
| `claude-login` | `claude-cli-auth` | `run_in_terminal` | `claude auth login` |
| `claude-auth-unverified` | `claude-cli-auth` | `run_in_terminal` | `claude auth status` não respondeu com o JSON esperado (versão antiga, erro ou 30 s sem resposta). O motor **não** abre o login nesse caso; a pessoa confere num terminal e roda de novo. |
| `standard-user-required` | `git`, `gh`, `claude-desktop` | `external` | Homebrew não deve rodar como root; rodar com a conta comum de instalação. |
| `claude-path` | `claude-cli` | `confirm` | `claude.addToPath` (Linux/macOS: incluir `~/.local/bin` no perfil do shell) |
| `desktop-login-confirm` | `claude-desktop-auth` | `confirm` | `desktop.loginConfirmed` |
| `package-manager-missing` | `git`, `gh` | `external` | instalar o gerenciador indicado |
| `privilege-required` | `git`, `gh` | `run_in_terminal` ou `external` | Com sudo disponível, abrir o motor como usuário normal em terminal interativo; sem sudo, pedir uma conta autorizada. |
| `agents-export` | `agents` | `external` | gerar/entregar o export público ao clone selecionado |
| `agents-export-stale` | `agents` | `external` | preservar o export antigo e gerar um novo correspondente à biblioteca do clone |
| `gh-apt-conflict` | `gh` | `external` | reconciliar configuração APT divergente, mantida sem sobrescrita |

No APT, keyring e lista compatíveis são reutilizados sem regravação. Arquivos
divergentes ou symlinks geram ação externa; mesmo arquivos criados anteriormente
pelo motor não são atualizados automaticamente. Arquivos novos usam criação
sem sobrescrita e têm hashes/propriedade registrados em um recibo local
`.hubicg-station-apt-<runId>.json` no diretório de configuração. Rotação de
chaves exige reconciliação explícita, preservando configurações administradas.

Pedido novo pode entrar no catálogo sem mudar a versão do contrato. A interface que não conhece um `id` usa o
tratamento genérico do `kind`.

---

## 6. Respostas da interface

A interface responde **rodando o motor de novo** com um arquivo de respostas:

```json
{
  "schema": "hubicg.station.answers/1",
  "answers": {
    "git.name": "Maria Silva",
    "git.email": "maria@exemplo.com.br",
    "desktop.loginConfirmed": true
  }
}
```

- O arquivo é JSON em UTF-8. Chave desconhecida é ignorada com um `log` de aviso.
- Escapes JSON são decodificados, inclusive Unicode e pares substitutos. Os tipos das chaves conhecidas são
  validados; JSON/envelope inválido ou tipo incorreto termina com código 2. Identidade não aceita NUL nem
  caracteres de controle. No bash, o leitor POSIX awk `json-read.awk` acompanha o motor na mesma pasta;
  não há dependência de Python ou jq na estação.
- Uma resposta só é usada se a etapa ainda precisar dela. Responder `git.name` com a identidade já configurada não
  muda nada.
- Resposta inválida (por exemplo, e-mail malformado) faz a etapa terminar em `action_required` de novo, com a
  explicação em `message`.
- **Nunca** ponha credencial no arquivo de respostas. Nenhuma chave do catálogo pede uma.
- A interface apaga o arquivo depois da execução.

Atalhos equivalentes, para uso no terminal: `-GitName`/`--git-name`, `-GitEmail`/`--git-email`,
`-ConfirmDesktopLogin`/`--confirm-desktop-login`, `-UseWindowsCertStore` e `--add-to-path`.

### 6.1 Ciclo típico de uma interface

```text
1. roda  motor --check --json --non-interactive         → mostra o relatório
2. roda  motor --json --non-interactive                 → mostra o progresso
3. se código 3: para cada action_required, abre o diálogo do kind
4. grava as respostas e volta ao passo 2 com --answers-file
5. código 0: concluído. Código 1: mostra as etapas failed e o log.
```

---

## 7. Códigos de saída

| Código | Significado | A interface deve |
|---|---|---|
| 0 | Concluído. Nada pendente. | Mostrar sucesso. |
| 1 | Pelo menos uma etapa terminou em `failed`. | Mostrar as falhas e oferecer o log. |
| 2 | Uso incorreto (opção ou etapa desconhecida). Nenhuma etapa rodou. | Tratar como defeito da interface. |
| 3 | Pendências do usuário (`action_required` ou `blocked`), sem falha. | Conduzir os pedidos e rodar de novo. |
| 4 | Pré-condição do sistema não atendida (sistema ou shell sem suporte). Nenhuma etapa rodou. | Explicar e encerrar. |
| 5 | Só em `--check` e `--dry-run`: há o que instalar ou configurar. | Oferecer aplicar. |
| 130 | Interrompido (Ctrl+C, encerrado pela interface). | Oferecer rodar de novo. |

Precedência quando vários se aplicam: 1, depois 3, depois 5.

---

## 8. Log

- Toda execução grava os mesmos eventos, um por linha, em um arquivo de log, além de emiti-los em `stdout`. O
  caminho vai em `run_start.data.logFile`.
- Padrão por sistema: Windows `%LOCALAPPDATA%\HubICG\station\logs`, Linux
  `${XDG_STATE_HOME:-~/.local/state}/hubicg/station/logs`, macOS `~/Library/Logs/HubICG/station`. Nome:
  `station-<runId>.jsonl`. O motor mantém os 20 mais recentes.
- **Sanitização, antes de qualquer gravação ou emissão:** credencial em URL vira `***`; trechos com forma de token
  (`gh[pousr]_…`, `github_pat_…`, `sk-ant-…`, `Bearer …`) são substituídos por `[redacted]`; o código de
  dispositivo **não** vai para o arquivo de log (só para `stdout`); e-mail e organização da conta Claude não são
  coletados.
- Saída de ferramenta só é registrada quando a etapa falha, já sanitizada e limitada a 4 KB.
- Nome e e-mail da identidade Git não são emitidos nas mensagens nem em `data`; a etapa informa apenas se a
  identidade já existia ou foi configurada. Erros de gravação da identidade não repassam a saída da ferramenta.

---

## 9. Versionamento e compatibilidade

O motor POSIX atende Linux e mantém suporte experimental ao macOS 13+ (x86_64/arm64). No macOS, usa Homebrew apenas se estiver
disponível; sua ausência mantém o pedido genérico `package-manager-missing`. O app Desktop existente
em `/Applications` ou `~/Applications` é preservado. Uma instalação nova usa somente `~/Applications`.
As consultas do Claude e o login de dispositivo do gh têm limite mesmo sem GNU timeout. A confirmação
do Desktop depende da pessoa na sessão gráfica; SSH não é evidência de login.

- `schema` muda de `/1` para `/2` somente em mudança **incompatível**: remover ou renomear campo, tipo de
  evento, status, `kind` ou código de saída, ou mudar o significado de um deles.
- Acrescentar etapa, campo em `data`, `id` de pedido, `type` de resposta ou status novo **não** muda a versão. A
  interface precisa tolerar isso (seção 3.1); status de `step_end` desconhecido deve ser tratado como `failed`
  para não esconder problema.
- Toda mudança incompatível exige revisão do contrato e dos consumidores.

---

## 10. Fora do contrato

- O texto humano do modo sem `-Json`.
- A ordem das chaves dentro dos objetos JSON.
- `stderr`.
- Variáveis `HUBICG_STATION_TEST_*`: ganchos de teste automatizado, nunca usados em produção.
