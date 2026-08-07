# v0.1.0 — Community Governance Foundation

## Implemented

- Python installation on Linux, macOS and Windows;
- configuration/role validation and status;
- local SQLite role import and text search with a compatible fallback;
- explained local role selection, source precedence and conflict detection;
- integrity-checked role backup, export and explicitly approved restore;
- portable and privacy-aware filename validation;
- configuration diff, proposal and explicit approval;
- hash-chained change evidence, history structure and manifest verification;
- read-only Git status;
- governance, security, contribution and licensing foundation.

## Compatibility matrix

| Operating system | Python 3.11 | Python 3.12 |
|---|---:|---:|
| Linux | CI required | CI required |
| macOS | CI required | CI required |
| Windows | CI required | CI required |

Every release candidate must pass all six jobs and the reproducible-build job.
The PR records the run and artifact IDs for its exact candidate commit.

## Planned, not implemented

Natural-language intent parsing, semantic role selection, any remote catalog
synchronization/API, model selection, MCP connectivity, context
compaction, token optimization, guardrail orchestration and adaptive history.

## Upgrade and rollback

Back up `.hubicg/`, install the new wheel, run `hubicg validate`, then exercise
read-only commands. To roll back, reinstall the prior wheel and restore the
compatible role backup using the exact approval ID. See
`docs/UPGRADE-ROLLBACK.md`. Future schema migrations require their own
compatibility and reverse-migration evidence.

The candidate artifacts and checksums are generated privately. The official
tag and GitHub Release are produced only after the legal gate.
