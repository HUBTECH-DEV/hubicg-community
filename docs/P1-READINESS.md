# P1 implementation and release-candidate readiness

**Scope:** approved Community baseline for v0.1.0

**Public status:** promotion and release authorized on 2026-08-07

## P1.1 — Community product and governance

| Criterion | Candidate evidence | State |
|---|---|---|
| Installable CLI | `pyproject.toml`, wheel and sdist | Implemented |
| Minimum journey | isolated wheel smoke test in `scripts/verify_release.py` | Implemented |
| Human approval | proposal ID required by `config apply` | Implemented |
| Change evidence | hash-chained `.hubicg/evidence/` events | Implemented |
| Community health | governance, contribution, security, support and templates | Implemented in candidate |
| Cross-platform CI | Linux, macOS and Windows; Python 3.11/3.12 | Enforced |
| Merge policy | squash-only, update branch allowed and merged branches deleted | Applied |
| Public-only GitHub controls | ruleset, CodeQL, dependency review, secret scanning and private vulnerability reporting | Configured; public workflow validation required before tag |

## P1.2 — Local role storage and selection

| Criterion | Candidate evidence | State |
|---|---|---|
| Public role schema | `schemas/role-v1.schema.json` | Implemented |
| Local database | SQLite schema v1 with WAL and integrity checks | Implemented |
| Search and selection | FTS5/fallback plus explained deterministic selector | Implemented |
| Multiple roles | count limit, source precedence and declared conflicts | Implemented |
| Language handling | case/accent normalization and language aliases/filters | Implemented baseline |
| Backup/export/rollback | hash-addressed backup, JSON export and approved restore | Implemented |
| Remote catalog or Atlas | research only | Not prioritized |

## P1.3 — First release

The technical release candidate produces:

- wheel and normalized source distribution;
- portable `SHA256SUMS`;
- SPDX 2.3 SBOM;
- unsigned, hash-bound `BUILD-PROVENANCE.json`;
- isolated-wheel `SMOKE-REPORT.json`;
- reproducibility evidence from two byte-identical builds;
- install, upgrade and rollback instructions;
- Linux/macOS/Windows CI evidence.

The word “unsigned” is deliberate: build provenance is not a substitute for the
approved signed tag. Every P0 gate and the explicit public authorization were
completed on 2026-08-07; promotion and release may proceed.
