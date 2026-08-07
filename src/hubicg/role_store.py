"""Local-first SQLite repository for private, project and cached official roles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .role_schema import validate_role

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RoleRecord:
    role_id: str
    name: str
    instructions: str
    source: str
    locale: str
    version: str
    content_hash: str


class SQLiteRoleRepository:
    """Store role metadata locally without a server or runtime dependency."""

    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> bool:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_metadata (
                    version INTEGER PRIMARY KEY
                );
                INSERT OR IGNORE INTO schema_metadata(version) VALUES (1);
                CREATE TABLE IF NOT EXISTS roles (
                    role_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    instructions TEXT NOT NULL,
                    source TEXT NOT NULL CHECK(source IN ('custom', 'project', 'official')),
                    locale TEXT NOT NULL DEFAULT 'und',
                    version TEXT NOT NULL DEFAULT '1',
                    content_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS roles_source_name ON roles(source, name);
                CREATE TABLE IF NOT EXISTS role_tags (
                    role_id TEXT NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
                    tag TEXT NOT NULL,
                    PRIMARY KEY(role_id, tag)
                );
                CREATE TABLE IF NOT EXISTS catalog_state (
                    catalog_id TEXT PRIMARY KEY,
                    revision TEXT NOT NULL,
                    manifest_hash TEXT NOT NULL
                );
                """
            )
            version = connection.execute("SELECT MAX(version) FROM schema_metadata").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise ValueError(f"unsupported role database schema: {version}")
            try:
                connection.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS roles_fts USING fts5(role_id UNINDEXED, name, instructions)"
                )
            except sqlite3.OperationalError:
                return False
        return True

    def upsert(self, payload: dict[str, Any], source: str) -> RoleRecord:
        if source not in {"custom", "project", "official"}:
            raise ValueError(f"unsupported role source: {source}")
        errors = validate_role(payload)
        if errors:
            raise ValueError("; ".join(errors))
        role_id = str(payload["id"]).strip()
        name = str(payload["name"]).strip()
        instructions = str(payload["instructions"]).strip()
        locale = str(payload.get("locale", "und")).strip() or "und"
        version = str(payload.get("version", "1")).strip() or "1"
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        content_hash = hashlib.sha256((canonical + "\n").encode()).hexdigest()
        record = RoleRecord(role_id, name, instructions, source, locale, version, content_hash)
        tags = sorted({str(tag).strip().casefold() for tag in payload.get("tags", []) if str(tag).strip()})
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO roles(role_id, name, instructions, source, locale, version, content_hash, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(role_id) DO UPDATE SET
                     name=excluded.name, instructions=excluded.instructions, source=excluded.source,
                     locale=excluded.locale, version=excluded.version,
                     content_hash=excluded.content_hash, payload_json=excluded.payload_json""",
                (role_id, name, instructions, source, locale, version, content_hash, canonical),
            )
            connection.execute("DELETE FROM role_tags WHERE role_id = ?", (role_id,))
            connection.executemany("INSERT INTO role_tags(role_id, tag) VALUES (?, ?)", ((role_id, tag) for tag in tags))
            try:
                connection.execute("DELETE FROM roles_fts WHERE role_id = ?", (role_id,))
                connection.execute(
                    "INSERT INTO roles_fts(role_id, name, instructions) VALUES (?, ?, ?)",
                    (role_id, name, instructions),
                )
            except sqlite3.OperationalError:
                pass
        return record

    def list(self) -> list[RoleRecord]:
        if not self.path.is_file():
            self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT role_id, name, instructions, source, locale, version, content_hash FROM roles ORDER BY name, role_id"
            ).fetchall()
        return [RoleRecord(**dict(row)) for row in rows]

    def payloads(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT payload_json, source, content_hash FROM roles ORDER BY name, role_id"
            ).fetchall()
        result = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload["_source"] = row["source"]
            payload["_contentHash"] = row["content_hash"]
            result.append(payload)
        return result

    def status(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"initialized": False, "schemaVersion": None, "roles": 0, "integrity": "not-initialized"}
        with self.connect() as connection:
            version = connection.execute("SELECT MAX(version) FROM schema_metadata").fetchone()[0]
            roles = connection.execute("SELECT COUNT(*) FROM roles").fetchone()[0]
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            fts5 = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'roles_fts'"
            ).fetchone()[0] == 1
        return {
            "initialized": True,
            "schemaVersion": version,
            "roles": roles,
            "integrity": integrity,
            "fts5": fts5,
        }

    def backup(self, target: Path) -> None:
        if not self.path.is_file():
            raise ValueError("role database is not initialized")
        target.parent.mkdir(parents=True, exist_ok=True)
        source = self.connect()
        destination = sqlite3.connect(target)
        try:
            source.execute("PRAGMA wal_checkpoint(FULL)")
            source.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("role database backup integrity check failed")
        finally:
            destination.close()
            source.close()

    def restore(self, source: Path) -> None:
        if not source.is_file() or source.is_symlink():
            raise ValueError("role database backup is not a regular file")
        uri = f"file:{source.as_posix()}?mode=ro"
        candidate = sqlite3.connect(uri, uri=True)
        try:
            if candidate.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("role database backup integrity check failed")
            version = candidate.execute("SELECT MAX(version) FROM schema_metadata").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise ValueError(f"unsupported role database schema: {version}")
        finally:
            candidate.close()

        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(prefix=".roles-restore.", dir=self.path.parent)
        os.close(descriptor)
        temp_path = Path(temp_name)
        try:
            candidate = sqlite3.connect(uri, uri=True)
            destination = sqlite3.connect(temp_path)
            try:
                candidate.backup(destination)
            finally:
                destination.close()
                candidate.close()
            if self.path.exists():
                current = self.connect()
                try:
                    current.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    current.execute("PRAGMA journal_mode = DELETE")
                finally:
                    current.close()
            os.replace(temp_path, self.path)
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(self.path) + suffix)
                if sidecar.exists():
                    sidecar.unlink()
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def search(self, query: str, limit: int = 10) -> tuple[list[RoleRecord], str]:
        if not self.path.is_file():
            self.initialize()
        tokens = [token for token in re.findall(r"[^\W_]+", query.casefold(), flags=re.UNICODE) if token]
        if not tokens:
            return [], "fallback"
        columns = "role_id, name, instructions, source, locale, version, content_hash"
        with self.connect() as connection:
            try:
                expression = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
                rows = connection.execute(
                    f"""SELECT r.{columns.replace(', ', ', r.')} FROM roles_fts
                        JOIN roles r USING(role_id) WHERE roles_fts MATCH ?
                        ORDER BY bm25(roles_fts), r.name LIMIT ?""",
                    (expression, limit),
                ).fetchall()
                return [RoleRecord(**dict(row)) for row in rows], "fts5"
            except sqlite3.OperationalError:
                rows = connection.execute(f"SELECT {columns} FROM roles ORDER BY name, role_id").fetchall()
        scored: list[tuple[int, RoleRecord]] = []
        for row in rows:
            record = RoleRecord(**dict(row))
            searchable = f"{record.role_id} {record.name} {record.instructions}".casefold()
            score = sum(searchable.count(token) for token in tokens)
            if score:
                scored.append((score, record))
        scored.sort(key=lambda item: (-item[0], item[1].name.casefold(), item[1].role_id))
        return [record for _, record in scored[:limit]], "fallback"
