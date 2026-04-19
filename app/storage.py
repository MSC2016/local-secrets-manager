import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class Storage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    def connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def file_exists(self) -> bool:
        return os.path.exists(self.db_path)

    def file_is_empty(self) -> bool:
        return self.file_exists() and os.path.getsize(self.db_path) == 0

    def has_schema(self) -> bool:
        if not self.file_exists() or self.file_is_empty():
            return False
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name IN ('app_meta', 'vaults', 'secrets')
                """
            ).fetchall()
            return {row["name"] for row in rows} == {"app_meta", "vaults", "secrets"}

    def initialize(self):
        with closing(self.connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS app_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vaults (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS secrets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vault_id INTEGER NOT NULL REFERENCES vaults(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    value_encrypted TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_accessed_at TEXT,
                    UNIQUE(vault_id, name)
                );
                """
            )
            conn.commit()

    def reset(self):
        if self.file_exists():
            os.remove(self.db_path)

    def list_all_secret_payloads(self) -> list[dict]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT vaults.name AS vault_name, secrets.name AS secret_name, secrets.value_encrypted
                FROM secrets
                INNER JOIN vaults ON vaults.id = secrets.vault_id
                ORDER BY vaults.name, secrets.name
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def replace_secret_payload(self, vault_name: str, secret_name: str, value_encrypted: str):
        with closing(self.connect()) as conn:
            vault_id = self._get_vault_id(conn, vault_name)
            result = conn.execute(
                """
                UPDATE secrets
                SET value_encrypted = ?, updated_at = ?
                WHERE vault_id = ? AND name = ?
                """,
                (value_encrypted, utc_now(), vault_id, secret_name),
            )
            if result.rowcount == 0:
                raise KeyError(secret_name)
            conn.commit()

    def get_meta(self, key: str) -> str | None:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

    def set_meta(self, key: str, value: str):
        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO app_meta(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            conn.commit()

    def list_vaults(self) -> list[dict]:
        with closing(self.connect()) as conn:
            rows = conn.execute("SELECT name, created_at, updated_at FROM vaults ORDER BY name").fetchall()
            return [dict(row) for row in rows]

    def create_vault(self, name: str):
        now = utc_now()
        with closing(self.connect()) as conn:
            conn.execute(
                "INSERT INTO vaults(name, created_at, updated_at) VALUES(?, ?, ?)",
                (name, now, now),
            )
            conn.commit()

    def rename_vault(self, current_name: str, new_name: str):
        now = utc_now()
        with closing(self.connect()) as conn:
            result = conn.execute(
                "UPDATE vaults SET name = ?, updated_at = ? WHERE name = ?",
                (new_name, now, current_name),
            )
            if result.rowcount == 0:
                raise KeyError(current_name)
            conn.commit()

    def delete_vault(self, name: str):
        with closing(self.connect()) as conn:
            result = conn.execute("DELETE FROM vaults WHERE name = ?", (name,))
            if result.rowcount == 0:
                raise KeyError(name)
            conn.commit()

    def _get_vault_id(self, conn: sqlite3.Connection, vault_name: str) -> int:
        row = conn.execute("SELECT id FROM vaults WHERE name = ?", (vault_name,)).fetchone()
        if not row:
            raise KeyError(vault_name)
        return int(row["id"])

    def list_secrets(self, vault_name: str) -> list[dict]:
        with closing(self.connect()) as conn:
            vault_id = self._get_vault_id(conn, vault_name)
            rows = conn.execute(
                """
                SELECT name, metadata_json, created_at, updated_at, last_accessed_at
                FROM secrets
                WHERE vault_id = ?
                ORDER BY name
                """,
                (vault_id,),
            ).fetchall()
            output = []
            for row in rows:
                item = dict(row)
                item["metadata"] = json.loads(item.pop("metadata_json"))
                output.append(item)
            return output

    def create_secret(self, vault_name: str, name: str, value_encrypted: str, metadata: dict):
        now = utc_now()
        with closing(self.connect()) as conn:
            vault_id = self._get_vault_id(conn, vault_name)
            conn.execute(
                """
                INSERT INTO secrets(vault_id, name, value_encrypted, metadata_json, created_at, updated_at, last_accessed_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (vault_id, name, value_encrypted, json.dumps(metadata), now, now, None),
            )
            conn.commit()

    def get_secret(self, vault_name: str, name: str) -> dict:
        with closing(self.connect()) as conn:
            vault_id = self._get_vault_id(conn, vault_name)
            row = conn.execute(
                """
                SELECT name, value_encrypted, metadata_json, created_at, updated_at, last_accessed_at
                FROM secrets
                WHERE vault_id = ? AND name = ?
                """,
                (vault_id, name),
            ).fetchone()
            if not row:
                raise KeyError(name)
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json"))
            return item

    def update_secret(self, vault_name: str, name: str, *, new_name: str | None = None, value_encrypted: str | None = None, metadata: dict | None = None):
        current = self.get_secret(vault_name, name)
        with closing(self.connect()) as conn:
            vault_id = self._get_vault_id(conn, vault_name)
            result = conn.execute(
                """
                UPDATE secrets
                SET name = ?, value_encrypted = ?, metadata_json = ?, updated_at = ?
                WHERE vault_id = ? AND name = ?
                """,
                (
                    new_name or current["name"],
                    value_encrypted or current["value_encrypted"],
                    json.dumps(metadata if metadata is not None else current["metadata"]),
                    utc_now(),
                    vault_id,
                    name,
                ),
            )
            if result.rowcount == 0:
                raise KeyError(name)
            conn.commit()

    def delete_secret(self, vault_name: str, name: str):
        with closing(self.connect()) as conn:
            vault_id = self._get_vault_id(conn, vault_name)
            result = conn.execute("DELETE FROM secrets WHERE vault_id = ? AND name = ?", (vault_id, name))
            if result.rowcount == 0:
                raise KeyError(name)
            conn.commit()

    def touch_secret(self, vault_name: str, name: str):
        with closing(self.connect()) as conn:
            vault_id = self._get_vault_id(conn, vault_name)
            result = conn.execute(
                "UPDATE secrets SET last_accessed_at = ? WHERE vault_id = ? AND name = ?",
                (utc_now(), vault_id, name),
            )
            if result.rowcount == 0:
                raise KeyError(name)
            conn.commit()
