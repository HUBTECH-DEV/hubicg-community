# HubICG repository centralization

HubICG uses two active repositories:

- `HUBTECH-DEV/hubicg-community`: canonical public open core;
- `HUBTECH-DEV/hubicg-enterprise`: private Enterprise overlay.

Community owns the CLI, public schemas, public roles, local storage contracts,
public governance, CI and releases. Enterprise consumes a reviewed Community
release or commit and must not maintain a separately edited copy of shared
Community functionality.

## Promotion direction

```text
Community change
  -> public review, CLA, CI, provenance and release
  -> Enterprise pin update and integration validation
```

Enterprise-only work does not move automatically into Community. Promotion to
the open core requires a deliberate public contribution, privacy review,
licensing and provenance validation.

The repositories `hubicg-community-provenance-private`, `codex-ai-ml-config`
and `codex-github-governance-platform` are historical provenance sources, not
active development destinations.
