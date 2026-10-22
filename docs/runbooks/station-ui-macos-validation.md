# Validação M1 — diálogos nativos macOS

Estado: **experimental; validação visual pendente**. Motor, instalação e autenticação são conduzidos exclusivamente pelo motor canônico da estação,
via `hubicg.station.event/1`. Não há cópia do motor ou de suas regras na GUI.

## Execução

Na conta de teste autorizada, pelo Terminal:

```sh
/caminho/do/clone/installers/station/ui/macos/Instalar-HubICG-Estacao.command
```

Por padrão, a GUI conduz `installers/station/hubicg-station.sh` do mesmo clone. Para um pacote aprovado
externo, passe `--engine /caminho/do/motor.sh` ou defina `HUBICG_STATION_ENGINE`; a opção prevalece sobre a
variável. A GUI não escolhe uma branch ou instala outro motor. A entrada `.command` precisa de permissão executável. O ambiente usa somente
bash e AppleScript/JXA/Foundation já disponíveis no macOS; Python e Node são ferramentas de testes locais.

## Roteiro visual único

Combine previamente uma janela de testes, preservando as sessões de autenticação em andamento.
Use uma conta gráfica de teste autorizada e preserve os arquivos e sessões existentes.

1. Abra a entrada `.command` com o motor externo liberado. Confira a origem exibida na tela de boas-vindas.
2. Clique em **Verificar computador**. Observe o progresso por etapa e o resultado item a item, inclusive
   TLS/rede, ferramentas ausentes e avisos de pré-requisitos. Capture somente a janela da GUI, preservando
   conteúdo de outras aplicações.
3. Se a máquina não atende aos pré-requisitos liberados, registre as pendências e cancele. Não instale
   Homebrew, CLT, pacotes administrativos nem repita apply para produzir sucesso artificial.
4. Quando houver autorização e pré-requisitos, selecione etapas e pasta do clone, confira a explicação dos
   logins e confirme **Instalar**. O progresso vem de eventos JSON do motor. **Interromper** termina o grupo
   do motor; nova execução verifica novamente o estado.
5. No resumo, use **Resolver pendências** apenas para ações que o usuário decidiu realizar. Nome/e-mail
   são validados localmente; respostas booleanas começam por **Não**. Pedidos manuais `run_in_terminal`
   e `external` abrem terminal/página por botão explícito. No pedido bloqueante `browser_code`, depois
   da confirmação de Instalar, a GUI abre a URL oficial se a ferramenta ainda não abriu, conforme §5.3
   do contrato. O código pode ser copiado; o motor aguarda a autorização no navegador.
6. **Verificar e continuar** grava respostas temporárias e executa novamente o motor; a GUI remove o
   arquivo depois da execução, inclusive no encerramento. Nunca forneça senha/token/cookie na GUI.
7. Registre o resumo, códigos e caminho do log. **Rodar de novo** inicia outra sessão de resumo;
   instalações anteriores não são contadas novamente como feitas nessa nova sessão. Instalação parcial
   e código 3 continuam parciais. Não confirme login Desktop sem o usuário verificar o aplicativo.

## Testes e evidências

`tests/station_ui/StationUi.Mac.Tests.js` cobre o estado do contrato, ações, validação, recuperação de eventos,
status desconhecido e resumo acumulado. Node é usado somente no desenvolvimento.
`tests/test_station_ui_macos.py` também verifica os lançadores e o adaptador de processos em POSIX.

No macOS, compile a entrada AppleScript com `osacompile`, execute
`tests/station_ui/StationUi.Mac.NativeChecks.js` com `osascript -l JavaScript` e rode
`Test-StationUiMacProcess.sh <pasta-macos>`. São testes sem janelas: não substituem o roteiro visual.
A fixture `tests/fixtures/station/macos-check-engine.sh` não instala nem autentica nada.

```sh
/usr/bin/osascript -l JavaScript /caminho/da/gui/installers/station/ui/macos/HubICG-Station-UI.js \
  /caminho/da/gui/installers/station/ui/macos --headless-check --engine /caminho/do/motor.sh
```

`--headless-check` nunca executa apply. Registre JSON, código do processo, hash do pacote, versão do motor,
conta/sistema, preservação dos arquivos e limitações. O check pode gerar o log sanitizado do próprio motor.
Presença/hash de um arquivo ou sucesso de parser não verifica conta corporativa nem carregamento de prompts.
Sem interação/captura autorizada, entregue o roteiro e mantenha a aprovação visual pendente, sem solicitar
Accessibility/Screen Recording ou instalar automação adicional por conta própria.

O contrato /1 (§3.2) trata ausência de `run_end` como 130, mantendo as pré-condições 2/4. A GUI também
mostra o código real do processo e informa relatório incompleto. Se um evento final anunciar sucesso e o
processo falhar depois, o resultado da GUI é falha, com diagnóstico da divergência.

Testes nativos anteriores sem janelas não constituem aceite visual nem comprovam autenticação dos aplicativos.
O login Codex CLI não foi testado nesta rodada; esse limite não bloqueia a entrega experimental.
