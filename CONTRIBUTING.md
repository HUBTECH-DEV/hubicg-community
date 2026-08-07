# Contributing

Thank you for helping HubICG. Follow the Code of Conduct and never include
private prompts, chat histories, credentials or employer-owned material.

## Issues and decisions

Use the bug, feature, documentation or configuration issue form before opening
a pull request. Include a minimal synthetic reproduction. Security reports
must use the private channel in `SECURITY.md`, never a public issue.

Cross-cutting changes to public contracts, compatibility, security, privacy,
licensing, editions or persistent data require an ADR under `docs/adr/`. The
core maintainer records acceptance, rejection or requested revision.

## Tests

Create a Python 3.11+ virtual environment, install the development tools, then
run:

```sh
python -m pip install -e . pytest build
make check
make test
```

Release-related changes must also run `make release-candidate` and preserve the
documented rollback path.

## Before code can be merged

1. Open or reference an issue; use an ADR proposal for cross-cutting decisions.
2. Accept the current Individual CLA, or have an authorized employer accept the
   Corporate CLA. Record the CLA version and hash.
3. Work in a focused branch and add tests and documentation.
4. Run `make check` and `make test`.
5. Open a pull request and complete its checklist.

Required checks, maintainer review and the CLA gate must pass. A contribution
is promoted through review, CI and merge; it does not confer maintainer status.

Maintainers may request additional provenance, threat analysis, migration or
compatibility evidence. A contribution is merged only when its scope belongs
to Community, tests and documentation match the implementation, and every
required review is resolved.

The CLA preserves authorship and gives HubTech sufficient rights to distribute
contributions under AGPL-3.0-only and separate commercial licenses. It does not
transfer contributor trademarks or unrelated work.

Community accepts features in the openly distributed core. Proprietary
enterprise integrations, customer material and commercial-only modules must not
be copied here. See `docs/EDITIONS.md`.
