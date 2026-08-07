# CLI contract

Global options precede commands: `hubicg --root PATH --json COMMAND`.

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

## Change evidence

```text
hubicg evidence changes verify
```

Every approved `config apply` appends a hash-chained event containing the
proposal ID and the before/after configuration hashes. Evidence contains no
prompt or chat content.

## Public filename gate

```text
hubicg files verify
```

The command evaluates tracked and non-ignored paths against
`.hubicg/filename-policy.json`. It rejects non-portable characters, ambiguous
case collisions, reserved device names, unsafe structures, excessive lengths
and filename tokens associated with secrets or personal documents. It reports
violations but never renames files automatically.
