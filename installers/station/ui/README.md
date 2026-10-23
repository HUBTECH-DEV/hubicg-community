# Interfaces gráficas do instalador da estação

Community #146. Contrato do motor: [`docs/architecture/station-installer-engine.md`](../../../docs/architecture/station-installer-engine.md)
(`hubicg.station.event/1`).

As interfaces **só conduzem o motor**: rodam a verificação, mostram o ambiente, deixam escolher as etapas e a
pasta do clone, acompanham a instalação pelos eventos JSON, conduzem os pedidos de ação e mostram o resumo.
Nenhuma reimplementa lógica de instalação, e nenhuma tem campo de senha ou token.

| Sistema | Interface | Ponto de entrada (clique duplo) | Motor conduzido |
|---|---|---|---|
| Windows | W1, assistente WinForms no Windows PowerShell 5.1 | `windows/Instalar-HubICG-Estacao.cmd` | `../hubicg-station.ps1` |
| Linux | L1, `zenity`; `kdialog` no KDE; terminal sem ambiente gráfico | `linux/hubicg-station.desktop` | `../hubicg-station.sh` |
| macOS | M1 experimental, diálogos AppleScript/JXA; validação visual pendente | `macos/Instalar-HubICG-Estacao.command` | `../hubicg-station.sh` |

## Arquivos

```text
station-ui-texts.json        textos pt-BR compartilhados (etapas, status, pedidos, códigos de saída)
windows/
  Instalar-HubICG-Estacao.cmd  clique duplo: abre o assistente no PS 5.1 (-STA, ExecutionPolicy só do processo)
  HubICG-Station-UI.ps1        a tela (WinForms)
  StationUi.Core.ps1           lógica sem tela: eventos, estado, argumentos, respostas, textos
linux/
  hubicg-station.desktop       clique duplo enquanto estiver na pasta do instalador (%k)
  hubicg-station-ui.sh         lançador; --criar-atalho cria o atalho no menu e na área de trabalho
  hubicg_station_ui.py         núcleo + frentes zenity, kdialog e terminal (Python 3, só biblioteca padrão)
macos/
  Instalar-HubICG-Estacao.command  entrada de clique duplo, motor do mesmo clone por padrão
  Instalar-HubICG-Estacao.applescript  entrada AppleScript alternativa (recebe a pasta macos)
  HubICG-Station-UI.js         diálogos Standard Additions e execução via Foundation/JXA
  StationUi.Core.js            estado, respostas e resumo pelo contrato /1
  StationUi.Process.sh         adaptador bash 3.2 com cancelamento do grupo
```

Os `.ps1` são UTF-8 **com BOM**: sem ele, o PowerShell 5.1 lê o arquivo como ANSI e um acento quebra uma string
longe do erro. O teste `tests/test_station_ui_windows.py` barra arquivo sem BOM ou com BOM duplicado.

Antes da instalação, gere o export público descrito em [../README.md](../README.md).
Se faltar no clone selecionado, o motor orienta a geração e a interface mostra a pendência.

## Como cada interface fala com o motor

```text
1. motor --check --json --non-interactive                → tela de verificação (ambiente item a item)
2. motor --json --non-interactive [--only ...] [--repo-dir ...]   → progresso por etapa
     browser_code (bloqueante): código em destaque, copiar, abrir a página; o motor segue sozinho
3. código 3: assistente de pendências (input, confirm, run_in_terminal, external)
4. grava o arquivo de respostas, volta ao passo 2 com --answers-file e apaga o arquivo depois
5. resumo: o que foi feito nesta instalação, o que já estava, o que falhou, e o caminho do log
   "Rodar de novo" começa outra passada: a segunda mostra tudo como "Já estava"
```

- A seleção padrão é tudo o que se aplica ao sistema; ela vai **sem** `--only`, para o motor reportar
  `unsupported` (e não `skipped`) no que não existe no sistema.
- O resumo acumula as execuções encadeadas (aplicação, respostas, nova aplicação): o que a primeira instalou não
  vira "Já estava" na segunda.
- `run_in_terminal` abre um terminal com o comando oficial e com o `PATH` atualizado (o motor pode ter acabado de
  instalar o `claude`); o motor confere o resultado na execução seguinte.
- Status de etapa desconhecido é mostrado como falha; campo desconhecido é ignorado (contrato, seção 9).
- Eventos ausentes geram aviso de relatório incompleto. O mapa final de `run_end` recupera os status das
  etapas que perderam `step_end`, mantendo explícita a ausência dos detalhes.
- No KDE, `kdialog` requer `qdbus` para acompanhar e interromper o progresso. Se esse controle não estiver
  disponível, a interface usa `zenity` ou terminal; se nenhum puder abrir, orienta a execução pelo terminal
  antes de iniciar o motor.

## Testar sem instalar nada

O motor simulado (`tests/fixtures/station/simulated_engine.py`) emite eventos válidos pelo schema e guarda estado
entre execuções. Ele aceita as opções das duas grafias (`-Json` e `--json`).

```powershell
# Windows: abre o assistente contra o motor simulado
$env:HUBICG_STATION_SIM_DELAY_MS = '150'
powershell -NoProfile -ExecutionPolicy Bypass -STA -File installers\station\ui\windows\HubICG-Station-UI.ps1 `
  -EnginePath tests\fixtures\station\simulated_engine.py

# Windows: percurso automático com capturas de tela de cada passo (abre a janela na sessão)
powershell -NoProfile -ExecutionPolicy Bypass -File tests\station_ui\Invoke-StationUiWalkthrough.ps1
```

O percurso salva as capturas em uma subpasta exclusiva `execucao-<id>` dentro de `-CaptureDir`.
Arquivos existentes na pasta informada são preservados, inclusive quando o percurso falha.

```sh
# Linux: o mesmo, em qualquer frente
HUBICG_STATION_SIM_DELAY_MS=150 installers/station/ui/linux/hubicg-station-ui.sh \
  --engine tests/fixtures/station/simulated_engine.py --frontend zenity   # ou kdialog, terminal
```

Cenários do simulador (`HUBICG_STATION_SIM_SCENARIO`): `default`, `fail`, `tls`, `repo-access`,
`terminal-login`, `code-timeout`, `invalid-email` e `unsupported-os`. O estado fica em
`HUBICG_STATION_SIM_STATE` (apague o arquivo para recomeçar do zero). `HUBICG_STATION_SIM_OS` simula outro
sistema.

Testes automatizados: `python -m unittest discover -s tests` (os do núcleo W1 rodam só no Windows; os da frente
zenity, só em POSIX). Validação real em VM: [`docs/runbooks/station-ui-vm-validation.md`](../../../docs/runbooks/station-ui-vm-validation.md).

## Acessibilidade

M1 usa somente componentes nativos do macOS; não exige Node, Python, Homebrew ou CLT para abrir
a interface. A geração do export público continua sendo uma etapa separada do motor.
`--engine` ou `HUBICG_STATION_ENGINE` permitem indicar um motor externo aprovado.
`--headless-check` executa somente a verificação, retorna JSON e o código de resultado; não comprova
interação visual, capturas ou login na sessão gráfica. M1 permanece **experimental, com validação
visual pendente**; login Codex CLI não foi testado nesta rodada. Veja o
[roteiro macOS](../../../docs/runbooks/station-ui-macos-validation.md).
O workflow `station-macos.yml` verifica JXA/AppleScript, processos e fixture sem janelas ou instalação real.

- Toda informação de situação está em texto, não só em cor; os controles têm nome acessível (lido pelo leitor de
  tela) e ordem de tabulação na ordem visual.
- W1: cores do sistema (respeita alto contraste), escala por DPI, `Enter` aciona o botão principal, `Esc`
  interrompe ou fecha (com confirmação), mnemônicos (`Alt+letra`), foco levado ao conteúdo de cada passo, campo
  inválido marcado com mensagem também na descrição acessível.
- L1: os diálogos são os nativos do desktop (`zenity`/`kdialog`), com o suporte de acessibilidade deles; o modo
  terminal funciona com leitor de tela de console.
