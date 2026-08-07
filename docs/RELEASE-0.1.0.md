# v0.1.0 — Community Governance Foundation

## Implemented

- Python installation on Linux, macOS and Windows;
- configuration/role validation and status;
- local SQLite role import and text search with a compatible fallback;
- portable and privacy-aware filename validation;
- configuration diff, proposal and explicit approval;
- history structure and checksum-manifest verification;
- read-only Git status;
- governance, security, contribution and licensing foundation.

## Compatibility matrix

| Operating system | Python 3.11 | Python 3.12 |
|---|---:|---:|
| Linux | CI required | CI required |
| macOS | CI required | CI required |
| Windows | CI required | CI required |

The matrix becomes release evidence only after all six GitHub Actions jobs pass.

## Planned, not implemented

Natural-language intent parsing, semantic role selection, official Atlas
catalog synchronization/API, model selection, MCP connectivity, context
compaction, token optimization, guardrail orchestration and adaptive history.

## Upgrade and rollback

Back up `.hubicg/`, install the new wheel, run `hubicg validate`, then exercise
read-only commands. To roll back, reinstall the prior wheel and restore the
compatible `.hubicg/` backup. The role database schema is initialized
explicitly with `hubicg roles db init`; future schema migrations will require
their own compatibility and rollback evidence.

The official tag, artifacts and checksums are produced only after the legal gate.
