# Governance

HubICG uses maintainer-led, evidence-based governance.

## Roles

- **Core maintainer:** Paulo Cesar Benjamin Junior. Owns releases, security
  decisions, governance changes, repository maintenance and final technical
  tie-breaking. Paulo is the sole appointed maintainer for v0.1.0.
- **Maintainer:** a contributor granted review or merge responsibility for a
  defined area in `MAINTAINERS.md`.
- **Contributor:** anyone proposing an issue, discussion, documentation or code.

Routine changes use issues and pull requests. Cross-cutting, security,
compatibility, data-governance or irreversible decisions require an ADR. The
core maintainer records the decision and rationale; no contributor gains merge
or commercial relicensing authority merely by contribution.

Sustained, sound and respectful contributions may lead to maintainership after
public nomination, scope definition and core-maintainer approval.

Maintainer scope, GitHub identity and appointment date must be recorded in
`MAINTAINERS.md`. Inactivity alone does not remove authorship. Merge authority
may be suspended or removed for security risk, repeated policy violations or
loss of the documented scope, with a recorded rationale and an opportunity to
respond when safe.

An organization or repository permission does not itself appoint a maintainer.
Accounts not listed in `MAINTAINERS.md` are not authorized by project
governance to maintain, push, merge or release HubICG Community.

Releases require passing CI, package and security checks, updated change and
migration notes, dependency/provenance review and core-maintainer approval.
Legal and public-release gates remain independent of technical readiness.
