# P0 repository maintainer gate

Paulo Cesar Benjamin Junior (`@paullobenjamin`) is the sole authorized core
maintainer and repository maintainer. This authority concerns Git repository
administration and does not change authorship or the patrimonial-rights chain.

Halini (`@halinibenjamin-pm`) is not authorized to maintain this repository.
Removing her direct repository grant is insufficient while she remains an
owner (`admin`) of the `HUBTECH-DEV` organization, because organization owners
inherit administration over every organization repository.

The gate closes only when:

1. `@paullobenjamin` retains repository administration;
2. `@halinibenjamin-pm` no longer has `admin`, `maintain` or `push` permission
   on this repository;
3. no team, organization role or base permission restores that access;
4. `MAINTAINERS.md`, `GOVERNANCE.md` and `CODEOWNERS` continue to name only
   Paulo;
5. the verified GitHub permission evidence is recorded and
   `.hubicg/gates/p0-maintainers.json` is set to `approved`.

Meeting this gate requires an organization-level decision: remove Halini from
`HUBTECH-DEV`, or downgrade her from owner to member and ensure that base/team
permissions give her no access to this repository. This project does not apply
that organization-wide change without explicit authorization.
