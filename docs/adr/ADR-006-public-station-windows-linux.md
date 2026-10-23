# ADR-006: Public station engines and Windows/Linux interfaces

Status: Proposed for maintainer acceptance in Community #146.

Community distributes one canonical station engine per shell and interfaces
that consume `hubicg.station.event/1`. The station is source-distributed,
independent of the Python package's existing CLI and version. The Windows
and Linux interfaces share texts and the event schema. macOS shell support
remains experimental; no macOS GUI is included.

The default origin is `HUBTECH-DEV/hubicg-community`. Agent artifacts come
from the packaged public library through `scripts/build_station_agents.py`,
which reuses the public Claude adapter and composes shared foundations.
No private library, histories or enterprise defaults are distributed.

Station transport markers pin the UTF-8 body after the frontmatter fence,
including expanded foundations. This existing installer format differs from
the CLI adapter's name/instruction hash; the CLI contract stays unchanged.
External artifacts must use the station format and come from a trusted source.
Missing artifacts require explicit action. Generation refuses differing or
unexpected existing files, and installation preserves edited destinations.

Authentication runs in official tools. Tests use fakes and temporary state;
VM and login acceptance are separate gates. No scanner, CLA, permission or
release-version changes are part of this decision. Rollback removes the source
integration through a reviewed revert; installed user files require individual
review and are never removed automatically as a rollback mechanism.
