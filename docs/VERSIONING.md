# Versioning, compatibility and releases

HubICG follows Semantic Versioning. Before 1.0, minor releases may change
experimental interfaces, but release notes identify migration impact. Stable
CLI exit codes and documented JSON fields are compatibility surfaces.

Releases occur when a milestone passes CI, provenance, licensing and security
review—not on a fixed calendar. Deprecations are announced for at least one
minor release when practical; security removals may be immediate. Each release
provides installation steps, OS matrix, checksums, SBOM/provenance artifacts,
upgrade notes and rollback instructions.

Rollback means reinstalling the prior tagged artifact and restoring a compatible
configuration backup. Never downgrade persistent data without a migration path.
