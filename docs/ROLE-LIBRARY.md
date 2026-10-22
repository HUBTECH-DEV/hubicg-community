# Official role library

The package ships the HubICG Principal role library under
`src/hubicg/library/`:

- `roles/*.json`: 65 roles in the composable `role-v2` contract;
- `foundations/*.json`: 17 shared foundations;
- `manifest.json`: library version, license, provenance, counts and the
  SHA-256 of every file.

It is offered under `AGPL-3.0-only`, like the rest of this repository.
HubTech and HubICG names and marks are not licensed by the AGPL.

## Provenance

The library is authored in `HUBTECH-DEV/hubicg-enterprise`, under
`.promptsLibrary/`. `manifest.json` records the source repository and the
exact revision of each import. Only role and foundation definitions are copied:
no runtime, private configuration, prompt history or customer material.

Shared text blocks that the source references as `{{shared:<id>}}` are expanded
during the import, so each published role is self-contained and readable on its
own.

## Updating the library

```sh
python scripts/import_role_library.py SOURCE_CHECKOUT \
  --repository HUBTECH-DEV/hubicg-enterprise --revision SOURCE_COMMIT --version X.Y.Z
python scripts/build_manifest.py
make check
make test
```

The import is deterministic: the same source revision produces the same bytes.
A content change increments the library `version`, and each changed role
increments its `roleVersion`. The pull request goes through the normal review,
provenance and CLA gates.

## Using it

`hubicg library install` copies the verified library into the machine database
(see `docs/CLI-CONTRACT.md`). Once installed, every project on the machine can
select the official roles, and a project or custom role with the same ID keeps
precedence over the official one.
