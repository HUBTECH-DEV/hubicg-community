# CLI contract

Global options precede commands: `hubicg --root PATH --home PATH --json COMMAND`.
`--home` selects the machine data directory; without it the CLI uses
`HUBICG_HOME`, then the platform user data directory.

| Exit | Meaning |
|---:|---|
| 0 | Operation completed or validation passed |
| 1 | Content or integrity validation failed |
| 2 | Invalid path or command input |
| 3 | Missing, invalid or mismatched human approval |
| 4 | External tool unavailable or failed |

JSON mode returns an object on standard output for success and on standard
error for failure. Additive JSON fields are compatible changes. Removing or
changing a field or exit-code meaning requires the versioning process.

## Role catalog commands

```text
hubicg roles search QUERY [--limit N]
hubicg roles select QUERY [--count 1..10]
hubicg roles db init
hubicg roles db status
hubicg roles db import [--source custom|project|official]
hubicg roles db backup
hubicg roles db export
hubicg roles db restore --approval BACKUP_ID
```

Search uses `.hubicg/state/roles.db` when initialized and otherwise searches
the project role JSON files. The local state database is private and ignored
by Git. FTS5 is used when available, with a deterministic local fallback.

`roles select` is case- and accent-insensitive, accepts the filters documented
in `docs/ROLE-SCHEMA-COMPATIBILITY.md`, explains its score and reports declared
conflicts. It never calls a network service.

Backups are addressed by the first 16 hexadecimal characters of their SHA-256.
Restoration requires that exact value as explicit approval and validates the
database before replacement.

Roles may use either public contract: `role-v1` or the composable `role-v2`
(see `docs/ROLE-SCHEMA-COMPATIBILITY.md`). Search, selection, export and the
Claude Code adapter read both.

## Official role library

```text
hubicg library verify
hubicg library status
hubicg library install
hubicg library show ROLE_ID
```

The package ships an official library of `role-v2` roles and shared
foundations under `hubicg/library/`, pinned by `manifest.json` (SHA-256 per
file). `verify` checks hashes, schemas and that every foundation a role
composes is shipped. `install` verifies first and then replaces the official
roles in the machine database `library.db` in one transaction; it is
idempotent, removes official roles the new library no longer ships and never
overwrites a role another source owns under the same ID.

| Platform | Default machine directory |
|---|---|
| Windows | `%LOCALAPPDATA%\HubICG` |
| macOS | `~/Library/Application Support/HubICG` |
| Linux and others | `$XDG_DATA_HOME/hubicg`, else `~/.local/share/hubicg` |

`install` is the only command that writes outside `.hubicg/`, and only to that
directory. Once installed, `roles select` and `roles search` include the
official roles, with `custom` and `project` roles taking precedence over an
official role with the same ID. Selection never creates the machine database.
`show` returns a role with the foundations it composes, in declared order.

## Claude Code adapter

```text
hubicg adapters claude-code diff
hubicg adapters claude-code propose
hubicg adapters claude-code apply --approval PROPOSAL_ID
```

Renders every valid local role as a Claude Code subagent file under
`.hubicg/exports/claude-code/<role-id>.md`, following the same propose/apply
approval flow as `config apply`. `propose` refuses roles with a mutual
`conflictsWith` in the exported set. `apply` never overwrites or deletes a
file in that directory unless it carries the `hubicg:managed` provenance
marker this adapter writes, so hand-authored files are never touched. See
`docs/architecture/CLAUDE-CODE-ADAPTER-STUDY.md`.

### Activating exported agents in Claude Code

`hubicg` itself never writes outside `.hubicg/`, so `.hubicg/exports/claude-code/`
is a staging area, not yet where Claude Code looks. Making an exported role an
active subagent is therefore a separate, human-run step, outside `hubicg`:

```sh
# Linux/macOS: symlink each exported file into .claude/agents/
mkdir -p .claude/agents
for f in .hubicg/exports/claude-code/*.md; do
  ln -sf "../../$f" ".claude/agents/$(basename "$f")"
done
```

```powershell
# Windows: copy (creating a symlink requires an elevated/Developer Mode shell)
New-Item -ItemType Directory -Force .claude\agents | Out-Null
Copy-Item .hubicg\exports\claude-code\*.md .claude\agents\ -Force
```

Symlinking (preferred where available) keeps `.claude/agents/` in sync with
every future `apply` automatically; copying requires re-running the copy
after each `apply`. Either way, only run this against a role you have
reviewed -- `hubicg` guarantees the *export* went through human-approved
`propose`/`apply`, not that the resulting file was reviewed before it starts
acting as a live subagent.

## Change evidence

```text
hubicg evidence changes verify
```

Every approved `config apply` or `adapters claude-code apply` appends a
hash-chained event containing the proposal ID and the before/after content
hashes. Evidence contains no prompt or chat content.

## Public filename gate

```text
hubicg files verify
```

The command evaluates tracked and non-ignored paths against
`.hubicg/filename-policy.json`. It rejects non-portable characters, ambiguous
case collisions, reserved device names, unsafe structures, excessive lengths
and filename tokens associated with secrets or personal documents. It reports
violations but never renames files automatically.
