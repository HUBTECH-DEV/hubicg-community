> Procedimento de aceite em VM; a presença deste roteiro não comprova execução real.
> A geração do export público requer Python 3.11+ no host de preparação; a GUI Windows não instala Python.

# Roteiro: validar as interfaces do instalador da estação em VM

Community #146. Interfaces: [`installers/station/ui`](../../installers/station/ui/README.md). Este roteiro é para
quem valida, numa VM limpa, o que os testes automatizados não alcançam: o sistema de verdade, o motor de verdade,
os logins de verdade e as capturas de tela para o PR.

> **macOS fica fora deste roteiro.** Não há GUI macOS distribuída neste recorte.

## O que se valida

| # | Critério da #83 | Como aparece |
|---|---|---|
| 1 | Verificação de ambiente item a item, com explicação de cada falha | Passo 2 da interface |
| 2 | Seleção do que instalar e da pasta do clone | Passo 3 |
| 3 | Progresso por etapa, alimentado pelos eventos do motor | Passo 4 |
| 4 | Autenticação: o que vai acontecer, fluxo oficial, código de dispositivo, espera; nenhum campo de senha ou token | Passo 4 e pendências |
| 5 | Resumo: instalado, já estava, falhou, caminho do log | Passo 5 |
| 6 | Nova execução idempotente: a segunda passada mostra "Já estava" | "Rodar de novo" |
| 7 | Ponto de entrada de clique duplo | `.cmd` no Windows, `.desktop` no Linux |

Tire uma captura de tela de **cada** passo (`Win+Shift+S` no Windows; `PrtSc` no Ubuntu) e nomeie
`NN-passo.png`. Anote o caminho do log que o resumo mostra e anexe o arquivo `.jsonl` (ele já sai sanitizado;
confira mesmo assim que não há token nem código de dispositivo nele).

## Pré-requisito comum

O motor real precisa estar na mesma árvore: `installers/station/hubicg-station.ps1` e
`installers/station/hubicg-station.sh`. A validação de aceite é com o motor real;
o simulador só confere a interface e não comprova instalação.

No host de preparação, com Python 3.11+ existente e o checkout Community completo, execute
`python scripts/build_station_agents.py` (`python3` no Linux). Leve para a VM
`installers/` **e** o export `.hubicg/exports/station-agents/`, preservando esses
caminhos sob a mesma pasta de transporte. `git archive` sozinho não inclui o export
ignorado pelo Git: acrescente-o explicitamente ao pacote. Não leve configuração,
históricos ou credenciais do host.

A GUI procura os agentes em `<clone escolhido>/.hubicg/exports/station-agents/`.
Ela não usa automaticamente o export que ficou ao lado do lançador. Depois que
o motor criar o clone, entregue o export nesse caminho, conforme os passos abaixo.
Não substitua uma pasta de export existente: verifique-a ou volte ao snapshot limpo.
Como alternativa explícita, com Python 3.11+ disponível na VM, execute o gerador
na raiz desse clone. Python não é um pré-requisito oculto da GUI Windows.
Não use a conta de trabalho para os logins quando a política exigir uma conta de teste.

## Windows (Hyper-V ou Windows Sandbox)

1. **VM limpa.** Windows Sandbox (Windows Pro/Enterprise: "Ativar ou desativar recursos do Windows" → Windows
   Sandbox) já nasce limpo a cada abertura. No Hyper-V, use um checkpoint "limpo" e volte a ele antes de cada
   rodada. Confirme que **não** há Git, GitHub CLI nem Claude Code: `where git gh claude` não acha nada.
2. **Copie** `installers\` e `.hubicg\exports\station-agents\` para
   `C:\Users\<você>\Downloads\hubicg\`, preservando a árvore. Se o Windows marcar os
   arquivos como baixados da internet, o `.cmd` lida com isso (ExecutionPolicy Bypass só no processo).
3. **Clique duas vezes** em `installers\station\ui\windows\Instalar-HubICG-Estacao.cmd`.
   - Esperado: abre a janela "Instalador da estação HubICG — Boas-vindas", sem janela de console sobrando.
4. **Verificar o computador.** Esperado: lista do ambiente (sistema, shell, administrador, winget, espaço livre,
   proxy, TLS, acesso a cada host, ferramentas) e a lista de etapas com "Falta instalar ou configurar". Clique em
   cada item com aviso e confira a explicação.
5. **Avançar → Seleção.** Mantenha tudo marcado; troque a pasta do clone por `C:\hubicg-teste\hubicg-community`
   pelo botão "Escolher…". Confira o bloco "Como serão os logins".
6. **Instalar.** Acompanhe o progresso geral e o da etapa. No login do GitHub:
   - o código aparece em destaque; "Copiar código" põe o código na área de transferência;
   - o navegador abre `https://github.com/login/device` (ou o próprio gh abre); digite o código e autorize;
   - o painel some sozinho e a instalação continua. **Em nenhum momento** a interface pede senha ou token.
7. **Pendências.** Esperado: "Identidade do Git" (nome e e-mail), "Login no Claude Code" (botão que abre um
   terminal com `claude auth login`) e "Login no Claude Desktop" (abra o app, entre e marque a confirmação).
   - Teste a validação: deixe o e-mail como `teste` e clique em "Verificar e continuar": o campo fica marcado.
   - Corrija, faça o login do Claude Code no terminal que abriu e confirme o Desktop.
   - A pendência de agentes ausentes é esperada. Após a criação do clone do passo 5,
     copie o export preparado para o caminho default desse clone, em PowerShell:

     ```powershell
     $selectedClone = 'C:\hubicg-teste\hubicg-community'
     $transport = Join-Path $HOME 'Downloads\hubicg'
     $destination = Join-Path $selectedClone '.hubicg\exports\station-agents'
     if (Test-Path -LiteralPath $destination) { throw 'Export já existe: confira ou restaure a VM limpa.' }
     New-Item -ItemType Directory -Force (Join-Path $selectedClone '.hubicg\exports') | Out-Null
     Copy-Item -LiteralPath (Join-Path $transport '.hubicg\exports\station-agents') -Destination $destination -Recurse
     ```

     Confira os arquivos entregues e clique em "Verificar e continuar" ou "Rodar de novo".
8. **Resumo.** Esperado: "Tudo pronto", grupo "Instalado ou configurado agora" com as etapas da instalação, o
   caminho do log, e os botões "Abrir a pasta do log" e "Copiar o caminho do log".
   Isso só vale com export presente e validado, agentes concretamente gravados e todos
   os logins resolvidos. Sem export, espere `agents-export` / `action_required`
   (código 3), registre aceite parcial e não marque "Tudo pronto" como atingido.
   Leve também o recibo `.hubicg-station-export.json` dentro da pasta exportada.
   Se a biblioteca do clone diferir da usada no host, espere `agents-export-stale`:
   preserve o export anterior sob outro nome, gere novamente a partir desse clone
   com Python 3.11+ explicitamente disponível (ou no host com o mesmo checkout),
   entregue o novo export ao caminho padrão e repita a aplicação. Sem esse passo,
   a atualização não atingiu o critério de sucesso.
9. **Rodar de novo.** Esperado: o resumo mostra **todas** as etapas em "Já estava pronto ou não se aplica".
10. **Interromper.** Rode de novo e clique em "Interromper" no meio: confirme a pergunta; o resumo diz que a
    execução foi interrompida e que rodar de novo é seguro. Rode de novo até "Tudo pronto".
11. **Rede corporativa (se houver).** Numa rede com inspeção TLS (Netskope e afins), confira na verificação o item
    "Conexão segura (TLS): Inspecionada pela rede corporativa", a explicação e, nas pendências, a pergunta
    "Certificados da rede corporativa".

Acessibilidade (5 minutos): navegue o assistente inteiro só com `Tab`, `Shift+Tab`, `Enter`, `Espaço` e `Esc`;
ligue o Narrador (`Ctrl+Win+Enter`) e confira que botões, listas e campos são anunciados com nome; ative um tema
de alto contraste e confira que nada some.

## Linux (Ubuntu Desktop 24.04 LTS)

1. **VM limpa** (GNOME Boxes, VirtualBox, Hyper-V com Ubuntu Desktop). Crie um snapshot "limpo". Confirme:
   `command -v git gh claude` não acha nada; `zenity --version` e `python3 --version` respondem (vêm no Ubuntu
   Desktop).
2. **Copie** `installers/` e `.hubicg/exports/station-agents/` para `~/Downloads/hubicg/`, preservando a árvore.
3. **Ponto de entrada.** Rode uma vez, num terminal:
   `~/Downloads/hubicg/installers/station/ui/linux/hubicg-station-ui.sh --criar-atalho`.
   - Esperado: "Instalar a estação HubICG" no menu de aplicativos e na área de trabalho. Na área de trabalho, se o
     GNOME pedir, clique com o botão direito → "Permitir execução". Abra pelo **clique duplo**.
   - Anote se o `.desktop` da própria pasta (`hubicg-station.desktop`) abre pelo gerenciador de arquivos: no
     GNOME Files ele costuma abrir como texto; no Dolphin (KDE), pergunta se pode executar.
4. Siga os passos 4 a 10 do Windows, com estas diferenças:
   - escolha como clone `~/github/hubicg-community`. Depois que o clone existir,
     entregue o export preparado ao caminho usado pela GUI (não execute o bloco PowerShell):

     ```sh
     selected_clone="$HOME/github/hubicg-community"
     destination="$selected_clone/.hubicg/exports/station-agents"
     if [ -e "$destination" ]; then
       printf '%s\n' 'Export já existe: confira ou restaure a VM limpa.'
     else
       mkdir -p "$selected_clone/.hubicg/exports"
       cp -R -- "$HOME/Downloads/hubicg/.hubicg/exports/station-agents" "$destination"
     fi
     ```

     Confira os arquivos e repita a aplicação pela GUI. Sem o export, a etapa de
     agentes permanece `action_required`, com o mesmo critério parcial do Windows;
   - "Claude Desktop" e "Login no Claude Desktop" aparecem como **"Não se aplica a este sistema"**;
   - nas pendências aparece "Comando claude no PATH" (responda Sim);
   - o login do Claude Code fica bloqueado até o PATH ser resolvido e aparece na rodada seguinte de pendências:
     isso é a dependência do contrato, não defeito;
   - o `sudo` do apt pede a **sua senha no terminal do sistema**, nunca na interface. Se o motor pedir isso como
     pendência, ela aparece como "Permissão de administrador".
5. **KDE (opcional).** Numa VM Kubuntu, confira que a interface usa `kdialog` (barra de progresso do KDE).
6. **Sem ambiente gráfico.** Num terminal de texto (`Ctrl+Alt+F3` ou SSH), rode
   `~/Downloads/hubicg/installers/station/ui/linux/hubicg-station-ui.sh`. Esperado: o modo terminal, com as
   mesmas perguntas em texto.

## Ensaio com o motor simulado

Para treinar o roteiro ou conferir só a interface (nada é instalado):

```powershell
# Windows, na raiz do repositório
$env:HUBICG_STATION_SIM_DELAY_MS = '150'
powershell -NoProfile -ExecutionPolicy Bypass -STA -File installers\station\ui\windows\HubICG-Station-UI.ps1 -EnginePath tests\fixtures\station\simulated_engine.py
```

```sh
# Linux, na raiz do repositório
HUBICG_STATION_SIM_DELAY_MS=150 installers/station/ui/linux/hubicg-station-ui.sh --engine tests/fixtures/station/simulated_engine.py
```

O simulador guarda estado em `%TEMP%\hubicg-station-sim-state.json` (Windows) ou
`/tmp/hubicg-station-sim-state.json` (Linux): apague para recomeçar. `HUBICG_STATION_SIM_SCENARIO=fail` mostra o
resumo com falha; `tls`, a rede corporativa; `terminal-login`, o login do GitHub pelo terminal.

## Ao terminar

Volte a VM ao snapshot limpo. Entregue: as capturas de cada passo, os logs `.jsonl` das execuções e a lista do que
divergiu deste roteiro (passo, esperado, observado).
