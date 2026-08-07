# Role schema and compatibility

The public role contract is `schemas/role-v1.schema.json`.

## Required fields

| Field | Meaning |
|---|---|
| `schemaVersion` | Contract version; currently `1.0` |
| `id` | Stable lowercase hyphenated identifier |
| `name` | Human-readable role name |
| `instructions` | Role behavior, without secrets or private data |

Optional fields are `version`, `locale`, `tags`, `capabilities` and
`conflictsWith`. Unknown fields are rejected so that misspellings do not
silently alter selection behavior.

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
```

Terms are case- and accent-insensitive. All free terms must match. Results
include their score and reasons. Source precedence is `custom`, `project`, then
`official`; the latter is only a reserved origin label and does not imply a
remote service. Declared conflicts prevent incompatible roles from being
composed in the same selection.

Selection is local and makes no network request.
