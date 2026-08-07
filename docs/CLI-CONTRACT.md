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
hubicg roles db init
hubicg roles db import [--source custom|project|official]
```

Search uses `.hubicg/state/roles.db` when initialized and otherwise searches
the project role JSON files. The local state database is private and ignored
by Git. FTS5 is used when available, with a deterministic local fallback.

## Public filename gate

```text
hubicg files verify
```

The command evaluates tracked and non-ignored paths against
`.hubicg/filename-policy.json`. It rejects non-portable characters, ambiguous
case collisions, reserved device names, unsafe structures, excessive lengths
and filename tokens associated with secrets or personal documents. It reports
violations but never renames files automatically.
