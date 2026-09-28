# Guia de revisão simultânea — adaptadores Claude Code e Codex

Este guia separa o worktree em trilhas independentes para revisão paralela.
Nenhuma trilha exige acesso externo ou credenciais.

## Trilha A — renderer e formato Codex

- `src/hubicg/adapters/codex.py`
- `tests/test_codex_adapter.py`

Verificar determinismo, cobertura do hash, escape TOML, marcador, conflitos e
normalização de nomes.

```text
python -m pytest -q tests/test_codex_adapter.py
```

## Trilha B — governança CLI e evidência

- `src/hubicg/cli.py`
- `src/hubicg/change_evidence.py`
- `tests/test_codex_adapter_cli.py`

Verificar integridade da proposta, exit code 3, preflight de arquivo manual,
remoção exclusiva de arquivo gerenciado, idempotência e cadeia de evidência.

```text
python -m pytest -q tests/test_codex_adapter_cli.py
```

## Trilha C — compatibilidade Claude e Windows

- `src/hubicg/adapters/claude_code.py`
- `tests/test_claude_code_adapter.py`
- `tests/test_claude_code_adapter_cli.py`
- `tests/test_cli.py`

Verificar compatibilidade da assinatura de hash, inclusão de todos os campos
renderizados, proteção contra overwrite manual e skip restrito ao erro real de
privilégio de symlink.

## Trilha D — arquitetura e contrato público

- `docs/adr/ADR-003-claude-code-adapter.md`
- `docs/adr/ADR-004-codex-custom-agent-adapter.md`
- `docs/architecture/CODEX-ADAPTER-DESIGN.md`
- `docs/CLI-CONTRACT.md`
- `README.md`
- `CHANGELOG.md`

Verificar que staging e promoção nativa são distintos e que modelo, effort,
sandbox, MCP, skills e credenciais permanecem fora do schema de role.

## Gate integrado

```text
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m hubicg --root . validate
.venv\Scripts\python.exe -m hubicg --root . files verify
.venv\Scripts\python.exe -m hubicg --root . evidence verify
.venv\Scripts\python.exe -m hubicg --root . evidence changes verify
git diff --check
```

## Fora do escopo desta revisão

- commit, push, PR ou publicação;
- promoção para `.codex/agents/` ou `.claude/agents/`;
- alteração de configuração, permissões ou credenciais das ferramentas;
- MCP, seleção de modelo e reasoning effort.
