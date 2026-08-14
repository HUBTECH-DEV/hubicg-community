# Community and Enterprise editions

Community contains the reusable, model-agnostic governance core: configuration
validation, roles, approval workflow, evidence checks and public interfaces. It
is the canonical public open core under AGPL-3.0-only.

Enterprise may add proprietary deployment, administration, commercial support,
compliance connectors and private-history capabilities. It must consume the
Community core through versioned boundaries and must not silently move
previously public Community functionality behind a commercial gate.

Community and Enterprise are intentionally different distributions. Shared
code changes originate here, pass public CI and provenance, and are then
consumed by Enterprise through a pinned release or commit.
