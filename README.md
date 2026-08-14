# HubICG Community

HubICG (HubTech Intent & Context Gateway) is a model-agnostic foundation for
governing AI configuration, roles, prompt context and auditable changes across
tools and IDEs.

> Community Governance Foundation v0.1.0. Publication, licensing, provenance
> and governance gates were approved on 2026-08-07.

## What v0.1.0 delivers

- a Python 3.11+ CLI with no runtime dependencies;
- deterministic configuration and role validation;
- portable and privacy-aware filename validation;
- local-first role indexing and search using SQLite;
- explained selection and conflict-aware composition of local roles;
- public Principal DevOps Engineer and Principal Git Engineer roles;
- verified local backup, export and approved rollback;
- human-approved configuration proposals;
- hash-chained evidence for applied configuration changes;
- prompt-history and evidence integrity checks;
- read-only Git status;
- machine-readable JSON output and stable exit codes.

Natural-language intent, provider routing, MCP connections, context compaction
and adaptive private history are roadmap items, not claims of this release.

## Install and use

```sh
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install .
hubicg --root . validate
hubicg --root . roles list
hubicg --root . roles verify
hubicg --root . roles search arquitetura
hubicg --root . roles select "arquitetura idioma:pt" --count 2
hubicg --root . roles db init
hubicg --root . roles db import --source project
hubicg --root . roles db backup
hubicg --root . roles db export
hubicg --root . files verify
hubicg --root . status
hubicg --root . config diff examples/config.proposed.json
hubicg --root . config propose examples/config.proposed.json
# Review the proposal, then use its printed ID:
hubicg --root . config apply --approval <proposal-id>
hubicg --root . evidence verify
hubicg --root . evidence changes verify
```

Mutating commands require explicit input and never write outside `.hubicg/`.
Use `--json` before the command for machine-readable output.

## Project health

- [Contribution guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Governance](GOVERNANCE.md)
- [Support](SUPPORT.md)
- [Versioning and compatibility](docs/VERSIONING.md)
- [Community and Enterprise boundary](docs/EDITIONS.md)
- [Repository centralization](docs/CENTRALIZATION.md)
- [Role storage and selection study](docs/architecture/ROLE-STORAGE-SELECTION-STUDY.md)
- [ADR-001: local role storage](docs/adr/ADR-001-local-role-storage.md)
- [Role schema and compatibility](docs/ROLE-SCHEMA-COMPATIBILITY.md)
- [Installation](docs/INSTALLATION.md)
- [Upgrade and rollback](docs/UPGRADE-ROLLBACK.md)
- [P1 readiness](docs/P1-READINESS.md)
- [P0 marks gate](docs/gates/P0-MARKS-GATE.md)
- [P0 provenance gate](docs/gates/P0-PROVENANCE-GATE.md)
- [P0 repository maintainer gate](docs/gates/P0-MAINTAINERS-GATE.md)
- [P0 publication authorization](docs/gates/P0-PUBLICATION-AUTHORIZATION.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

## Licensing

The intended public Community edition is licensed under `AGPL-3.0-only`.
HubTech may separately offer commercial terms for code over which it has
sufficient rights. See [LICENSING.md](LICENSING.md).

Copyright © 2026 Paulo Cesar Benjamin Junior, author. The patrimonial rights
holder is HUBTECH CONSULTORIA E DESENVOLVIMENTO LTDA under the documented
gratuitous assignment.
