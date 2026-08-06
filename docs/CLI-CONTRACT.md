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
