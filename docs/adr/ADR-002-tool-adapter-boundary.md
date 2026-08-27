# ADR-002 — Fronteira de adaptadores para ferramentas de IA (Claude, Codex e outras)

- **Estado:** proposto
- **Data:** 27/08/2026
- **Decisores:** Paulo Cesar Benjamin Junior, core maintainer

## Contexto

O README declara o HubICG como fundação agnóstica a modelo, e o núcleo atual
(`src/hubicg/role_schema.py`, `role_store.py`, `role_selection.py`) cumpre
isso: uma role é só `schemaVersion`, `id`, `name`, `instructions` e metadados,
sem nenhum campo específico de ferramenta. O README também lista "provider
routing" e "MCP connections" como itens de roadmap ainda não implementados.

Na prática, cada assistente de codificação agentic espera as instruções em uma
convenção própria de arquivo e injeção — por exemplo Claude Code lê
`CLAUDE.md`/system prompt, e o OpenAI Codex CLI lê `AGENTS.md`/config próprio.
Hoje o HubICG não produz nenhum desses artefatos: a seleção de roles
(`hubicg roles select`) devolve texto para o humano copiar, e não existe
exportação para o formato nativo de nenhuma ferramenta.

Sem uma decisão explícita, o caminho mais fácil para "funcionar com o Codex"
é acoplar lógica específica do Codex (ou do Claude) dentro do `role_store`/
`role_selection`, o que viola o objetivo de agnosticismo de modelo e o
Consequência #4 do ADR-001 ("evolução do seletor local independente de
provedor ou serviço remoto").

## Decisão

1. O núcleo de roles, seleção, config e evidência permanece 100% agnóstico:
   nenhuma ferramenta de IA é citada por nome em `src/hubicg/role_schema.py`,
   `role_store.py` ou `role_selection.py`.
2. Suporte a uma ferramenta específica (Claude Code, Codex CLI, ou outra) é
   implementado como um **adaptador de exportação** somente-leitura: um módulo
   que lê o resultado já determinístico de `roles select`/`roles list` e
   renderiza no formato nativo daquela ferramenta (ex.: `CLAUDE.md`,
   `AGENTS.md`), sem nunca escrever fora de onde o próprio HubICG já escreve
   hoje (`.hubicg/` e, quando explicitamente pedido, o arquivo de destino da
   ferramenta).
3. Todo adaptador consome exclusivamente o contrato público já estável (role
   schema v1 + saída de `roles select`); nenhum adaptador pode exigir mudança
   de schema para existir.
4. Adaptadores ficam isolados em um namespace próprio (ex.:
   `src/hubicg/adapters/<ferramenta>.py`), cada um com seus próprios testes,
   para que adicionar ou remover suporte a uma ferramenta não altere o núcleo.
5. Nenhum adaptador é "padrão"/prioritário no núcleo; a ordem em que
   ferramentas são suportadas é decisão de roadmap, não de arquitetura.
6. Fica fora desta ADR: chamadas de rede a qualquer API de modelo, MCP,
   detecção automática de qual ferramenta está rodando, e qualquer forma de
   telemetria. Isso permanece roadmap não decidido aqui.

## Consequências

### Positivas

- "Usar com o Codex" e "usar com o Claude" tornam-se a mesma mudança de
  arquitetura (adicionar um adaptador), não dois esforços divergentes;
- o núcleo continua testável e revisável sem depender do formato de nenhuma
  ferramenta externa;
- uma ferramenta nova (ou uma mudança de formato de uma existente) não é uma
  mudança cross-cutting no schema, só a adição/atualização de um adaptador.

### Custos e riscos

- cada ferramenta suportada é superfície adicional de manutenção e teste;
- divergência de convenções entre ferramentas (uma lê um arquivo, outra um
  diretório, outra variáveis de ambiente) pode pressionar por abstrações
  prematuras no adaptador — deve ser resistida até haver dois ou mais
  adaptadores reais para generalizar;
- exportar para o arquivo nativo de uma ferramenta (ex. sobrescrever
  `CLAUDE.md`) é uma escrita fora de `.hubicg/`; precisa do mesmo modelo de
  aprovação humana já usado por `config apply`, não escrita silenciosa.

## Alternativas avaliadas

- **Lógica de ferramenta dentro do núcleo de seleção:** rejeitada — quebra o
  agnosticismo de modelo que é o propósito declarado do projeto.
- **Um "formato universal" único que toda ferramenta deveria ler:** rejeitada
  por ora — HubICG não controla o que Claude Code ou Codex CLI leem; exigiria
  mudança fora do nosso controle.
- **Detecção automática da ferramenta ativa e exportação implícita:** adiada
  para uma ADR própria; risco de escrita não solicitada em arquivos do
  usuário sem aprovação explícita.

## Itens explicitamente adiados

Qual ferramenta ganha o primeiro adaptador (Claude, Codex, ambas em paralelo),
o formato exato de cada exportação, e a interação com MCP ficam fora desta
ADR e exigem proposta própria antes da implementação, conforme
`CONTRIBUTING.md`.

## Evidência associada

Ver [`docs/architecture/ROLE-STORAGE-SELECTION-STUDY.md`](../architecture/ROLE-STORAGE-SELECTION-STUDY.md)
e o schema público em [`schemas/role-v1.schema.json`](../../schemas/role-v1.schema.json).
