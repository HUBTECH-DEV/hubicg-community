"""Official role library: packaged definitions and the machine-wide database.

The library ships inside the ``hubicg`` package (``hubicg/library/``) as
``role-v2`` roles, shared foundations and a manifest with SHA-256 per file.
``install`` copies it into a SQLite database that belongs to the machine, not
to a project, so every project on the machine selects from the same official
roles. Roles and foundations are stored as JSON; the role-to-foundation link
is a view over that JSON (``json_each``), not a second copy of the data.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from importlib import resources
from pathlib import Path
from typing import Any

from .role_schema import validate_foundation, validate_role
from .role_store import SQLiteRoleRepository, write_role

CATALOG_ID = "hubicg-role-library"
DATABASE_NAME = "library.db"


def machine_home(override: str | None = None) -> Path:
    """Return the per-machine HubICG data directory.

    Precedence: explicit override, ``HUBICG_HOME``, then the platform's user
    data directory.
    """
    value = override or os.environ.get("HUBICG_HOME")
    if value:
        return Path(value).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "HubICG"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "HubICG"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "hubicg"


def database_path(home: Path) -> Path:
    """Return the resolved database path, refusing a redirected target.

    Policy for links: the machine directory itself and ``library.db`` must not
    be symbolic links, because they are what ``install`` writes. Ancestors are
    resolved instead of refused, since operating systems link them on purpose
    (``/var`` on macOS, for example), and the resolved path is what commands
    report, so the real write location is always visible.
    """
    for candidate in (home, home / DATABASE_NAME):
        if candidate.is_symlink():
            raise ValueError(f"refusing symbolic link: {candidate}")
    return home.resolve() / DATABASE_NAME


def _packaged() -> Any:
    return resources.files("hubicg") / "library"


def load_packaged() -> tuple[dict[str, Any], str, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Read the packaged library and verify it before anyone writes it anywhere.

    Returns the manifest, its SHA-256, roles, foundations and the errors found:
    hash mismatch, schema violation, count mismatch, or a role composing a
    foundation that the library does not ship.
    """
    root = _packaged()
    try:
        manifest_bytes = (root / "manifest.json").read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return {}, "", [], [], [f"manifest.json: unreadable: {error}"]
    if not isinstance(manifest, dict) or not isinstance(manifest.get("version"), str):
        return {}, "", [], [], ["manifest.json: must be an object with a version"]
    errors: list[str] = []
    loaded: dict[str, list[dict[str, Any]]] = {"roles": [], "foundations": []}
    validators = {"roles": validate_role, "foundations": validate_foundation}
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        return manifest, "", [], [], ["manifest.json: counts must be an object"]
    for kind in ("foundations", "roles"):
        entries = manifest.get(kind, [])
        if not isinstance(entries, list) or counts.get(kind) != len(entries):
            errors.append(f"{kind}: manifest count does not match its entries")
            continue
        for entry in entries:
            if not isinstance(entry, dict) or not all(isinstance(entry.get(key), str) for key in ("id", "path", "sha256")):
                errors.append(f"{kind}: manifest entry needs id, path and sha256")
                continue
            try:
                payload = (root / entry["path"]).read_bytes()
            except OSError as error:
                errors.append(f"{entry['path']}: unreadable: {error}")
                continue
            if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                errors.append(f"{entry['path']}: checksum mismatch")
                continue
            try:
                data = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                errors.append(f"{entry['path']}: invalid JSON: {error}")
                continue
            invalid = [f"{entry['path']}: {error}" for error in validators[kind](data)]
            if invalid:
                # An invalid document never reaches the composition check,
                # which assumes the shape the schema guarantees.
                errors += invalid
                continue
            if data.get("id") != entry["id"]:
                errors.append(f"{entry['path']}: id does not match the manifest")
                continue
            loaded[kind].append(data)
    known = {foundation["id"] for foundation in loaded["foundations"]}
    for role in loaded["roles"]:
        unknown = sorted(set(role.get("foundations", [])) - known)
        if unknown:
            errors.append(f"{role.get('id')}: composes unknown foundations: {', '.join(unknown)}")
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    return manifest, digest, loaded["roles"], loaded["foundations"], errors


class LibraryRepository(SQLiteRoleRepository):
    """Machine-wide database: the role schema plus foundations.

    It reuses role database schema 1 unchanged and adds two objects that the
    project database never needs, so it is a separate file rather than a
    migration of existing project databases.

    Only ``install`` writes. It leaves the database as a single file (rollback
    journal, not WAL), and every query opens it read-only, so selection,
    search and status never create or change anything in the machine
    directory.
    """

    def reader(self) -> sqlite3.Connection:
        # as_uri() percent-encodes the path, so '?' or '#' in a directory name
        # cannot leak into the URI query.
        connection = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> bool:
        fts5 = super().initialize()
        connection = self.connect()
        try:
            with connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS foundations (
                        foundation_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        version TEXT NOT NULL,
                        content_hash TEXT NOT NULL,
                        payload_json TEXT NOT NULL CHECK(json_valid(payload_json))
                    );
                    CREATE VIEW IF NOT EXISTS role_foundations AS
                        SELECT r.role_id AS role_id,
                               CAST(j.key AS INTEGER) AS position,
                               j.value AS foundation_id
                        FROM roles AS r, json_each(r.payload_json, '$.foundations') AS j
                        WHERE json_extract(r.payload_json, '$.schemaVersion') = '2.0';
                    """
                )
        finally:
            connection.close()
        return fts5

    def install(
        self, manifest: dict[str, Any], manifest_hash: str,
        roles: list[dict[str, Any]], foundations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Replace the official library in one transaction.

        Roles another source owns under the same ID are left untouched and
        reported, because ``custom`` and ``project`` take precedence over
        ``official``. Official roles that the new library no longer ships are
        removed.
        """
        fts5 = self.initialize()
        connection = self.connect()
        try:
            with connection:
                existing = dict(connection.execute("SELECT role_id, source FROM roles").fetchall())
                shipped = {role["id"] for role in roles}
                skipped = sorted(role_id for role_id in shipped if existing.get(role_id, "official") != "official")
                removed = sorted(
                    role_id for role_id, source in existing.items()
                    if source == "official" and role_id not in shipped
                )
                for role_id in removed:
                    connection.execute("DELETE FROM roles WHERE role_id = ?", (role_id,))
                    if fts5:
                        connection.execute("DELETE FROM roles_fts WHERE role_id = ?", (role_id,))
                for role in roles:
                    if role["id"] not in skipped:
                        write_role(connection, role, "official")
                connection.execute("DELETE FROM foundations")
                for foundation in foundations:
                    canonical = json.dumps(foundation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    connection.execute(
                        "INSERT INTO foundations(foundation_id, name, version, content_hash, payload_json)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (
                            foundation["id"], foundation["name"], foundation["version"],
                            hashlib.sha256((canonical + "\n").encode()).hexdigest(), canonical,
                        ),
                    )
                connection.execute(
                    """INSERT INTO catalog_state(catalog_id, revision, manifest_hash) VALUES (?, ?, ?)
                       ON CONFLICT(catalog_id) DO UPDATE SET
                         revision=excluded.revision, manifest_hash=excluded.manifest_hash""",
                    (CATALOG_ID, str(manifest["version"]), manifest_hash),
                )
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode = DELETE")
        finally:
            connection.close()
        return {
            "roles": len(shipped) - len(skipped),
            "foundations": len(foundations),
            "skipped": skipped,
            "removed": removed,
            "fts5": fts5,
        }

    def installed(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"installed": False}
        try:
            connection = self.reader()
        except sqlite3.OperationalError:
            return {"installed": False}
        try:
            state = connection.execute(
                "SELECT revision, manifest_hash FROM catalog_state WHERE catalog_id = ?", (CATALOG_ID,)
            ).fetchone()
            roles = connection.execute("SELECT COUNT(*) FROM roles WHERE source = 'official'").fetchone()[0]
            foundations = connection.execute("SELECT COUNT(*) FROM foundations").fetchone()[0]
        except sqlite3.OperationalError:
            return {"installed": False}
        finally:
            connection.close()
        if state is None:
            return {"installed": False}
        return {
            "installed": True,
            "version": state["revision"],
            "manifestHash": state["manifest_hash"],
            "roles": roles,
            "foundations": foundations,
        }

    def show(self, role_id: str) -> dict[str, Any] | None:
        """Return a role with the foundations it composes, in declared order."""
        if not self.path.is_file():
            return None
        connection = self.reader()
        try:
            row = connection.execute(
                "SELECT payload_json, source, content_hash FROM roles WHERE role_id = ?", (role_id,)
            ).fetchone()
            if row is None:
                return None
            foundations = connection.execute(
                """SELECT f.payload_json FROM role_foundations AS rf
                   JOIN foundations AS f USING(foundation_id)
                   WHERE rf.role_id = ? ORDER BY rf.position""",
                (role_id,),
            ).fetchall()
        finally:
            connection.close()
        return {
            "role": json.loads(row["payload_json"]),
            "source": row["source"],
            "contentHash": row["content_hash"],
            "foundations": [json.loads(item["payload_json"]) for item in foundations],
        }
