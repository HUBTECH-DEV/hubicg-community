# Estudo — o que falta para o HubICG funcionar plenamente com o Claude Code

**Escopo:** primeiro adaptador previsto pela [ADR-002](../adr/ADR-002-tool-adapter-boundary.md).
Este documento não é uma ADR; é o estudo que fundamenta uma futura ADR-003
("Claude Code adapter"), como o
[estudo de armazenamento de roles](ROLE-STORAGE-SELECTION-STUDY.md) fundamentou
o ADR-001.

## O que o Claude Code de fato lê

Levantamento direto das superfícies de configuração do Claude Code (não é
suposição — é o comportamento real do produto):

| Superfície | Arquivo | Escopo | Formato |
|---|---|---|---|
| Contexto sempre carregado | `CLAUDE.md` (raiz e subpastas) / `~/.claude/CLAUDE.md` | projeto ou usuário | markdown livre |
| Subagentes invocáveis | `.claude/agents/<nome>.md` | projeto ou usuário | frontmatter YAML (`name`, `description`, `tools`, `model`) + corpo = system prompt |
| Skills invocáveis por `/nome` | `.claude/skills/<nome>/SKILL.md` | projeto ou usuário | frontmatter (`name`, `description`) + corpo |
| Slash commands | `.claude/commands/<nome>.md` | projeto ou usuário | markdown livre |
| Permissões, hooks, modelo | `.claude/settings.json` / `settings.local.json` | projeto ou usuário | JSON |
| Servidores MCP | `.mcp.json` | projeto | JSON |
| Memória durável | diretório de memória do projeto | por sessão/projeto | markdown com frontmatter (`name`, `description`, `metadata.pinned`) |

Nenhuma dessas superfícies tem hoje qualquer noção de "role" agnóstica — cada
uma é específica do Claude Code.

## Por que subagentes, não `CLAUDE.md`, é o alvo certo

Uma role do HubICG (`schemas/role-v1.schema.json`) já é: `id` (slug curto),
`name`, `instructions` (até 20000 caracteres), `capabilities`/`tags`,
`conflictsWith`, `locale`, `version`. `roles select` devolve um subconjunto
determinístico, pontuado e sem conflito.

Despejar todas as roles selecionadas dentro de um único `CLAUDE.md` perde
exatamente o que o ADR-001 construiu: seleção determinística, explicada e
consciente de conflito vira só um bloco de texto fixo, sem fronteira entre
roles e sem re-seleção por tarefa.

Um subagente (`.claude/agents/<id>.md`) mapeia 1:1 com uma role:

| Campo da role | Campo do subagente |
|---|---|
| `id` (já casa com `^[a-z0-9]+(-[a-z0-9]+)*$`) | nome do arquivo, sem transformação |
| `name` | título/`name` no frontmatter |
| `instructions` | corpo do arquivo (system prompt do subagente) |
| `tags` + `capabilities` | texto de `description` (é o que o Claude Code usa para decidir quando acionar o subagente automaticamente) |
| `version` | comentário de proveniência no topo do arquivo, não existe campo nativo |
| `conflictsWith` | **não** vira campo do Claude Code; é aplicado antes da exportação — o adaptador recusa exportar duas roles conflitantes ao mesmo tempo |

Um `CLAUDE.md` gerado pode, no máximo, ser um índice fino (lista com link para
os subagentes exportados) dentro de um bloco marcado — nunca a cópia das
instruções.

## Fluxo de escrita: reaproveitar aprovação humana, não inventar um novo

Exportar toca arquivos fora de `.hubicg/`, o que hoje só acontece através do
par `config propose` → `config apply --approval ID`. O adaptador do Claude
Code precisa do mesmo contrato, não de um caminho de escrita direta:

```text
hubicg adapters claude-code diff
hubicg adapters claude-code propose
hubicg adapters claude-code apply --approval PROPOSAL_ID
```

Consequências diretas do contrato existente (`docs/CLI-CONTRACT.md`):

- exit code `3` para aprovação ausente/inválida/incompatível, igual a
  `config apply`;
- `--json` disponível antes do comando;
- nenhuma chamada de rede.

## Marcação de propriedade e idempotência

Todo arquivo gerado carrega um cabeçalho de proveniência, por exemplo:

```markdown
<!-- hubicg:managed role=principal-git-engineer version=1.0.0 hash=sha256:... -->
```

Regras:

1. `apply` sem mudança de role produz diff vazio (idempotente).
2. O adaptador se recusa a sobrescrever um arquivo em `.claude/agents/` que
   não tenha o marcador — protege subagentes escritos manualmente pelo
   usuário.
3. Quando uma role é desselecionada ou apagada, o `apply` seguinte remove o
   arquivo correspondente **somente se** ele carregar o marcador; nunca deixa
   órfão silencioso, nunca apaga o que não foi gerado por ele.

## Evidência

Cada `apply` do adaptador acrescenta um evento em `.hubicg/evidence/`
encadeado por hash, no mesmo formato usado por `config apply` (ID da
proposta, hash do estado antes/depois) — a exportação para Claude Code fica
auditável como qualquer outra mudança governada.

## Explicitamente fora do escopo de "funcionar plenamente"

- `settings.json`/`settings.local.json` (permissões, hooks, modelo): é
  fronteira de segurança do próprio Claude Code, HubICG não deve tocar;
- `.mcp.json`: adiado no ADR-002 junto com MCP em geral;
- skills e slash commands: roles do HubICG são contexto/instrução, não
  fluxos de comando; podem ser um adaptador futuro separado, não este;
- `CLAUDE.md` como destino primário: rejeitado acima, no máximo um índice.

"Funcionar plenamente com o Claude Code" aqui significa: toda role
selecionável via `hubicg roles select` pode ser exportada como subagente
funcional, com aprovação humana, idempotência e evidência — não significa
cobrir toda superfície de configuração do Claude Code.

## Testes exigidos antes de aceitar a ADR-003

- golden-file por role → subagente (conteúdo exato do frontmatter e corpo);
- idempotência: `apply` duas vezes sem mudança de role não altera o arquivo;
- rejeição de exportação quando duas roles selecionadas têm `conflictsWith`
  mútuo;
- recusa de sobrescrita de arquivo sem marcador `hubicg:managed`;
- remoção de arquivo gerado quando a role correspondente é removida da
  seleção, preservando arquivos não marcados;
- validação de que o frontmatter gerado é YAML válido com os campos que o
  Claude Code exige.

## Itens em aberto para a ADR-003

- exportar para o escopo de projeto (`.claude/agents/`) e/ou usuário
  (`~/.claude/agents/`) — provavelmente projeto por padrão, usuário como
  opção explícita;
- se `roles select` deve ganhar um modo "exportar tudo que bate no filtro"
  distinto do `--count` usado para leitura humana;
- nome exato do comando (`adapters claude-code` vs. `export claude-code`) —
  manter consistência com o restante do CLI-CONTRACT.md.
