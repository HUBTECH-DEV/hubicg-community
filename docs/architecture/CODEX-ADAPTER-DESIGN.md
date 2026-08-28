# Desenho — adaptador HubICG para OpenAI Codex

**Estado:** implementado localmente para revisão  
**Data:** 28/08/2026  
**Escopo:** equivalente Codex do primeiro adaptador previsto pelo
[ADR-002](../adr/ADR-002-tool-adapter-boundary.md), tomando como baseline o
[adaptador Claude Code](CLAUDE-CODE-ADAPTER-STUDY.md).

## 1. Resultado do levantamento do conector Claude Code

O conector existente não é uma integração de rede nem um cliente de modelo. É
um adaptador local de exportação de roles, composto pelos seguintes pontos:

| Ponto | Implementação atual | Responsabilidade |
|---|---|---|
| Fronteira arquitetural | `docs/adr/ADR-002-tool-adapter-boundary.md` | mantém schema, store e seleção agnósticos; isola formato de ferramenta |
| Estudo do formato nativo | `docs/architecture/CLAUDE-CODE-ADAPTER-STUDY.md` | escolhe subagente como mapeamento 1:1 de role e exclui MCP/permissões |
| Renderer puro | `src/hubicg/adapters/claude_code.py` | converte role v1 em Markdown com frontmatter, marcador e hash |
| Orquestração CLI | `src/hubicg/cli.py` | implementa `diff`, `propose` e `apply --approval` |
| Estado gerado | `.hubicg/exports/claude-code/<role-id>.md` | respeita a fronteira de escrita do HubICG |
| Evidência | `src/hubicg/change_evidence.py` | registra evento append-only encadeado por hash |
| Contrato público | `docs/CLI-CONTRACT.md` | documenta comandos, saída, aprovação e limites |
| Testes unitários | `tests/test_claude_code_adapter.py` | golden file, hash, marcador, conflito e idempotência |
| Testes CLI | `tests/test_claude_code_adapter_cli.py` | diff/proposta/aprovação/escrita e proteção de arquivo manual |

Fluxo observado:

```text
.hubicg/roles/*.json
        |
        v
role schema v1 + validação de conflitos
        |
        v
render_subagent(role)                 (puro, sem filesystem/rede)
        |
        v
diff -> propose -> apply --approval   (governança humana)
        |
        +--> .hubicg/exports/claude-code/*.md
        |
        +--> .hubicg/evidence/*.json  (cadeia de hashes)
```

Há uma inconsistência documental a corrigir em incremento próprio: o estudo
descreve remoção de export órfão e proteção contra sobrescrita em
`.claude/agents/`, enquanto a implementação atual exporta somente para
`.hubicg/exports/claude-code/`. O desenho Codex adota como contrato o
comportamento implementado: geração em staging interno; promoção para o
diretório nativo permanece separada.

## 2. Superfícies nativas do Codex

O Codex separa responsabilidades que não devem ser fundidas pelo HubICG:

| Superfície | Local de projeto | Uso correto no HubICG |
|---|---|---|
| Orientação persistente | `AGENTS.md` e `AGENTS.override.md` | regras do repositório, comandos, verificação e convenções; não é o destino primário de roles |
| Custom agents | `.codex/agents/<nome>.toml` | destino nativo 1:1 de uma role HubICG |
| Configuração | `.codex/config.toml` | defaults de sessão/agentes; fora do adaptador de roles |
| Skills | diretórios com `SKILL.md` | workflows reutilizáveis; fora deste primeiro adaptador |
| MCP | configuração `mcp_servers`/CLI | ferramentas e dados externos; fora deste adaptador |

Cada custom agent exige `name`, `description` e `developer_instructions`. O
arquivo pode também conter modelo, reasoning effort, sandbox, MCP e skills,
mas esses campos alteram segurança, custo ou capacidade. O adaptador não deve
inferi-los a partir de uma role v1.

## 3. Decisão proposta

Criar `hubicg adapters codex` como adaptador irmão de `claude-code`.

O renderer produz um TOML por role em:

```text
.hubicg/exports/codex/<role-id>.toml
```

Uma promoção futura, regida por ADR específica, poderá copiar somente arquivos
gerenciados para:

```text
.codex/agents/<role-id>.toml
```

`AGENTS.md` não será gerado nem alterado neste incremento. Roles representam
especializações invocáveis; `AGENTS.md` representa orientação persistente e
hierárquica do repositório. Misturá-los faria todas as roles incidirem em toda
tarefa e perderia seleção e isolamento.

## 4. Mapeamento role v1 -> custom agent Codex

| Role HubICG | Custom agent Codex | Regra |
|---|---|---|
| `id` | nome do arquivo e `name` | preservar o slug; substituir `-` por `_` apenas em `name` se validação real do Codex exigir |
| `name` | prefixo humano de `description` | preservar legibilidade |
| `tags` + `capabilities` | restante de `description` | formar orientação curta de quando usar |
| `instructions` | `developer_instructions` multiline | preservar conteúdo, normalizar somente newline final |
| `version` | comentário de proveniência | não há campo nativo de versão |
| `conflictsWith` | validação pré-render | recusar o conjunto conflitante; não serializar |
| `locale` | comentário/metadado de proveniência | não altera configuração de sessão |

Exemplo proposto:

```toml
# hubicg:managed role=principal-git-engineer version=1.0.0 hash=sha256:...
name = "principal_git_engineer"
description = "Principal Git Engineer. Use for: git, governance, branch-strategy."
developer_instructions = """
Inspecionar worktree antes de propor mudanças.
"""
```

O hash deve cobrir a representação canônica de todos os campos que influenciam
a saída, não apenas `name` e `instructions`:

```text
sha256(canonical_json({id, name, instructions, version, tags, capabilities, locale}))
```

Isso evita que uma mudança somente em `description` passe sem alteração do
marcador.

### Escape TOML obrigatório

O renderer deve usar string literal multiline quando possível e possuir uma
função explícita e testada para sequências que encerrariam o delimitador. Não
deve montar TOML assumindo que `instructions` é seguro. A saída precisa ser
validada por um parser TOML da biblioteca padrão (`tomllib`) nos testes.

## 5. Componentes propostos

```text
src/hubicg/adapters/codex.py
  content_hash(role) -> str
  codex_agent_name(role_id) -> str
  render_custom_agent(role) -> str
  parse_marker(text) -> ManagedMarker | None
  find_conflicts(roles) -> list[tuple[str, str]]

src/hubicg/cli.py
  codex_export_dir(ctx)
  codex_export_candidate(ctx)
  codex_existing_exports(export_dir)
  codex_diff(ctx, args)
  codex_propose(ctx, args)
  codex_apply(ctx, args)

src/hubicg/change_evidence.py
  record_codex_export(...)

tests/test_codex_adapter.py
tests/test_codex_adapter_cli.py
```

Contrato CLI:

```text
hubicg adapters codex diff
hubicg adapters codex propose
hubicg adapters codex apply --approval PROPOSAL_ID
```

Não é recomendável extrair agora uma abstração genérica de adaptadores. O
Claude produz Markdown/YAML e o Codex produz TOML, com regras diferentes de
nome, escape e validação. Depois de dois adaptadores implementados, podem ser
extraídos apenas os mecanismos comprovadamente idênticos: snapshot, diff,
proposal ID, apply e evidência.

## 6. Fluxo desenhado

```text
                         +-----------------------------+
                         | .hubicg/roles/*.json        |
                         | role schema v1              |
                         +--------------+--------------+
                                        |
                              validar + conflitos
                                        |
                                        v
                         +-----------------------------+
                         | adapters/codex.py           |
                         | renderer puro role -> TOML  |
                         +--------------+--------------+
                                        |
                         +--------------+--------------+
                         |                             |
                         v                             v
              +--------------------+        +---------------------+
              | diff/propose       |        | parser TOML/checks  |
              | nenhuma escrita    |        | determinismo/hash   |
              +---------+----------+        +---------------------+
                        |
                 aprovação explícita
                        |
                        v
              +-----------------------------+
              | apply atômico               |
              +--------------+--------------+
                             |
                +------------+-------------+
                |                          |
                v                          v
  .hubicg/exports/codex/*.toml   .hubicg/evidence/*.json
                |
                | incremento futuro + ADR + aprovação separada
                v
       .codex/agents/*.toml
```

## 7. Regras de segurança e propriedade

1. Nenhuma chamada à OpenAI, MCP ou outro serviço.
2. Nenhum token, login ou credencial no artefato.
3. Nenhuma geração de `model`, `model_reasoning_effort`, `sandbox_mode`,
   `mcp_servers` ou `skills.config` a partir de role v1.
4. Escrita somente em `.hubicg/exports/codex/` neste incremento.
5. Apply atômico e somente após proposal ID válido.
6. Arquivo sem marcador na primeira linha é tratado como manual e protegido.
7. Remoção somente de arquivo marcado e pertencente ao adaptador Codex.
8. Conflito entre roles bloqueia toda a proposta; não produzir export parcial.
9. Todo apply gera evidência append-only encadeada por hash.
10. Promoção a `.codex/agents/` exige decisão separada sobre merge, colisão,
    rollback e comportamento quando já existe arquivo manual.

## 8. Critérios de aceite

- golden file role -> TOML exato;
- `tomllib.loads()` aceita todo arquivo gerado;
- campos obrigatórios `name`, `description`, `developer_instructions` presentes;
- escape correto de aspas, barras, Unicode e delimitador multiline;
- nome Codex determinístico e sem colisão entre IDs;
- hash muda quando qualquer campo renderizado muda;
- render e segundo apply idempotentes;
- conflito de roles retorna erro antes da proposta;
- approval ausente, incorreto ou de outro tipo retorna exit code `3`;
- arquivo manual nunca é sobrescrito ou removido;
- role removida elimina somente seu export gerenciado;
- falha no meio do apply não deixa conjunto parcial;
- cadeia de evidência continua válida após múltiplos applies;
- `--json` mantém contrato equivalente ao adaptador Claude.

## 9. Incrementos executados e futuros

1. **Executado — ADR-004:** formato, staging e exclusões aceitos.
2. **Executado — renderer puro:** `codex.py`, golden tests e validação TOML.
3. **Executado — CLI governada:** diff/propose/apply e evidência específica.
4. **Executado — compatibilidade:** os adaptadores permanecem fora do núcleo
   de schema, store e seleção.
5. **Futuro — promoção nativa opcional:** decidir, em ADR separada, escrita em
   `.codex/agents/`, proteção de arquivos manuais e rollback.
6. **Futuro:** avaliar índice fino em `AGENTS.md`, pacote de skills ou
   plugin HubICG. Esses artefatos têm semântica distinta de role.

## 10. Decisões adotadas

- o primeiro incremento termina no staging `.hubicg/exports/codex/`;
- `name` usa underscore e o ID/arquivo preserva hífen;
- a primeira versão exporta todas as roles locais válidas;
- o evento é específico: `codex-export-applied`;
- ADR-003 registra retrospectivamente o Claude e ADR-004 decide o Codex.

## 11. Fontes de validação do Codex

- OpenAI, *Customization*: orientação persistente em `AGENTS.md`, workflows em
  skills, sistemas externos via MCP e especialização/delegação via subagents.
- OpenAI, *Subagents*: custom agents de projeto em `.codex/agents/*.toml`, com
  `name`, `description` e `developer_instructions` obrigatórios.
- OpenAI, *AGENTS.md*: descoberta hierárquica, overrides e limite combinado de
  instruções; reforça que esse arquivo deve permanecer pequeno e orientado ao
  repositório.

O helper oficial local do manual Codex não pôde ser atualizado neste ambiente
por falha Windows Schannel de verificação de revogação de certificado
(`CRYPT_E_NO_REVOCATION_CHECK`). As superfícies acima foram então confirmadas
na documentação oficial online e também confrontadas com o Codex CLI 0.146.0
instalado localmente.
