# Changelog

## [Unreleased]

### Added

- Composable `role-v2` contract and shared foundation contract; the CLI reads
  `role-v1` and `role-v2` (ADR-005).
- Official role library packaged with the CLI: 65 `role-v2` roles and 17
  foundations, pinned by a SHA-256 manifest.
- Machine-wide SQLite role library (`hubicg library verify | status | install
  | show`), stored as JSON with the role-to-foundation link derived by
  `json_each`; selection and search include it below project roles.
- `foundation:` / `fundamento:` selection filter.
- Canonical Community/Enterprise repository boundary and promotion direction.
- Public Principal DevOps Engineer and Principal Git Engineer roles.
- Community governance and legal-readiness documents.
- Auditable HubICG CLI foundation and cross-platform CI.
- Portable, privacy-aware filename policy and CI gate.
- Local-first SQLite role index, import and search foundation.
- Local role storage decision and exploratory study of remote alternatives.
- Public role schema, explained multilingual selection and conflict handling.
- Integrity-checked role backup, deterministic export and approved restore.
- Hash-chained evidence for approved configuration changes.
- Reproducible release build, isolated wheel smoke test and build provenance.

## [0.1.0] — 2026-08-07

Release name: Community Governance Foundation.

The legal, provenance, trademark and publication gates were approved. The
signed tag and public release were published with verified artifacts.
