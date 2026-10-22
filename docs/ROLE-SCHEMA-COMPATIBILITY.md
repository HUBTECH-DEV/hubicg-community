# Role schema and compatibility

There are two public role contracts. The CLI reads both, and every command
that consumes a role (validation, search, selection, export and adapters)
accepts either.

| Contract | Schema | `schemaVersion` | Shape |
|---|---|---|---|
| `role-v1` | `schemas/role-v1.schema.json` | `1.0` | One `instructions` text |
| `role-v2` | `schemas/role-v2.schema.json` | `2.0` | Structured `blocks`, composed `foundations`, `proficiency` P0–P4 |

Shared foundations follow `schemas/foundation.schema.json`. The official
library (`hubicg/library/`) uses `role-v2` exclusively; ADR-005 records why.

## Required fields of `role-v1`

| Field | Meaning |
|---|---|
| `schemaVersion` | Contract version; currently `1.0` |
| `id` | Stable lowercase hyphenated identifier |
| `name` | Human-readable role name |
| `instructions` | Role behavior, without secrets or private data |

Optional fields are `version`, `locale`, `tags`, `capabilities` and
`conflictsWith`. Unknown fields are rejected so that misspellings do not
silently alter selection behavior.

## Required fields of `role-v2`

| Field | Meaning |
|---|---|
| `schemaVersion` | `2.0` |
| `id`, `name` | As in `role-v1` |
| `roleVersion` | Role content version; content changes increment it |
| `foundations` | IDs of the shared foundations the role always rests on, in order of specificity |
| `proficiency` | Entries of `tool`, `level` (`P0` to `P4`) and `scope` |
| `blocks` | Ordered sections of `heading` and `body` |

Optional fields are `area`, `section`, `seniority`, `lead`, `locale`,
`extends`, `specializations`, `tags`, `capabilities` and `conflictsWith`.
Unknown fields are rejected. A role's searchable text is its `lead`, blocks
and proficiency, in that order.

The level rule of the official library: a tool central to the role's domain is
`P3` or `P4`, an adjacent one `P1` or `P2`, and the scope states where the
decision belongs to a person or to another role.

## Compatibility policy

- adding an optional field is backward compatible within schema `1.x`;
- tightening validation, adding a required field, removing a field or changing
  its meaning requires a new schema major version;
- role content changes require a role `version` change;
- role IDs remain stable; replacement uses a new ID and a documented migration;
- the CLI must read every schema version it writes;
- a database schema migration requires backup, integrity verification and a
  tested rollback path before release.

## Local selection contract

`hubicg roles select` accepts natural terms and optional filters:

```text
source:custom | fonte:custom | origen:custom
lang:pt-BR | idioma:pt-BR
tag:architecture | etiqueta:architecture
cap:solution-design | capacidade:solution-design
foundation:flow-delivery | fundamento:flow-delivery
```

Terms are case- and accent-insensitive. All free terms must match. Results
include their score and reasons. Source precedence is `custom`, `project`, then
`official`; `official` is the packaged library installed in the machine
database, never a remote service. Declared conflicts prevent incompatible roles from being
composed in the same selection.

Selection is local and makes no network request.
