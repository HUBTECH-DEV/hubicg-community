# ADR-003 — Adaptador de exportação para Claude Code

- **Estado:** aceito retrospectivamente
- **Data:** 28/08/2026
- **Decisores:** Paulo Cesar Benjamin Junior, core maintainer

## Contexto

O ADR-002 isolou integrações específicas em adaptadores, mas deixou formato e
destino em aberto. O primeiro adaptador implementado converte role schema v1
em subagente Claude Code.

## Decisão

1. Cada role válida é renderizada como Markdown de subagente.
2. O destino governado é `.hubicg/exports/claude-code/<role-id>.md`.
3. O fluxo público é `diff`, `propose` e `apply --approval`.
4. O marcador de proveniência contém role, versão e hash de todo campo
   renderizado.
5. Arquivos sem marcador são preservados e nunca sobrescritos.
6. Conflitos entre roles bloqueiam a exportação completa.
7. Cada apply aprovado registra evidência append-only encadeada por hash.
8. Escrita em `.claude/agents/`, MCP, settings, skills e comandos ficam fora
   deste ADR.

## Consequências

O HubICG produz artefatos auditáveis sem controlar a configuração ativa do
Claude Code. A promoção ao diretório nativo continua sendo uma decisão humana
separada.
