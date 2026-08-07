# Upgrade and rollback

## Before an upgrade

1. Verify the downloaded artifacts against `SHA256SUMS`.
2. Back up the local role database:

   ```sh
   hubicg --root . roles db backup
   ```

3. Record the printed 16-character backup ID.
4. Back up `.hubicg/config.json` using the deployment owner's protected backup
   process.
5. Export portable role definitions:

   ```sh
   hubicg --root . roles db export
   ```

## Upgrade

Install the approved wheel, then run:

```sh
hubicg --root . validate
hubicg --root . roles verify
hubicg --root . roles db status
hubicg --root . evidence changes verify
```

## Roll back local role data

Restoration is destructive to the active local role database and therefore
requires the exact backup ID:

```sh
hubicg --root . roles db restore --approval <backup-id>
```

The CLI verifies the backup SHA-256 prefix, SQLite integrity and schema version
before replacing the active database. It does not restore configuration or
chat history.

## Roll back the CLI

Reinstall the previously approved wheel, restore only a schema-compatible role
backup, and rerun all validation commands. Never downgrade persistent data
across an incompatible schema without a documented reverse migration.
