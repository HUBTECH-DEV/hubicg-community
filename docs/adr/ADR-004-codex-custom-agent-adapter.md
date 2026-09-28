# ADR-004 — Adaptador de custom agents para OpenAI Codex

- **Estado:** aceito
- **Data:** 28/08/2026
- **Decisores:** Paulo Cesar Benjamin Junior, core maintainer

## Contexto

O Codex usa custom agents TOML para especializações invocáveis. `AGENTS.md`
tem semântica diferente: orientação persistente e hierárquica do repositório.
O HubICG precisa preservar essa separação e a fronteira de escrita do ADR-002.

## Decisão

1. Cada role válida é renderizada em TOML com `name`, `description` e
   `developer_instructions`.
2. IDs com hífen são normalizados para underscore apenas no campo `name`; o
   nome do arquivo e a proveniência preservam o ID original.
3. O destino governado é `.hubicg/exports/codex/<role-id>.toml`.
4. A primeira versão exporta todas as roles locais válidas, como o adaptador
   Claude Code.
5. O fluxo público é `diff`, `propose` e `apply --approval`.
6. O evento de evidência é específico: `codex-export-applied`.
7. Arquivos sem marcador são preservados e nunca sobrescritos.
8. Conflitos e colisões de nome bloqueiam a exportação completa.
9. Modelo, reasoning effort, sandbox, MCP, skills e credenciais não são
   inferidos do schema de role.
10. `AGENTS.md`, `.codex/config.toml` e `.codex/agents/` não são alterados.

## Consequências

O resultado é consumível após promoção humana para `.codex/agents/`, mas o
HubICG não muda automaticamente a configuração ativa do Codex. Um incremento
futuro poderá propor promoção e rollback em ADR separada.

## Evidência externa

A documentação oficial do Codex descreve custom agents de projeto em
`.codex/agents/*.toml` e exige `name`, `description` e
`developer_instructions`.

## Revisão

Revisado por Claude (a pedido do maintainer) em 28/08/2026, cobrindo o código
já implementado (`src/hubicg/adapters/codex.py`, CLI, testes) contra esta
decisão. Um defeito real foi encontrado e corrigido nesse incremento: o
escape de string TOML (`toml_string`) não cobria o caractere DEL (U+007F),
que `json.dumps` não escapa mas `tomllib` rejeita; corrigido com escape
explícito e teste de regressão (`test_render_escapes_unescaped_del_control_character`).

Pendência conhecida e aceita para acompanhamento futuro: o item 2
(normalização de hífen para underscore em `name`) não tem confirmação
empírica com o Codex CLI local de que o underscore é exigido — a tentativa
de verificação falhou porque a instalação local do Codex CLI 0.146.0 não tem
o helper de sandbox do Windows (`codex-windows-sandbox-setup.exe` ausente).
A decisão foi mantida por ser de baixo impacto e reversível (afeta somente o
campo `name` do TOML gerado, não a governança, a evidência ou a integridade
do export).
