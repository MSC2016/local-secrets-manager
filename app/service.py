import json
import os
import sqlite3
import threading
import time
from urllib.parse import quote

from app.crypto import decrypt_value, encrypt_value
from app.models import LockedError, NotFoundError, StorageError, ValidationError
from app.session import SessionState
from app.storage import Storage


VERIFY_TEXT = "local-dev-secrets-manager"


class SecretsService:
    def __init__(self, db_path: str, config_path: str):
        self.storage = Storage(db_path)
        self.config_path = config_path
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        self.session = SessionState()
        self._load_config()
        self._start_timeout_watcher()

    def _start_timeout_watcher(self):
        def watch():
            while True:
                self.session.apply_timeout()
                time.sleep(1)

        threading.Thread(target=watch, daemon=True).start()

    def _load_config(self):
        defaults = {
            "timeout_enabled": True,
            "timeout_minutes": 15,
            "reset_on_read": True,
            "lock_on_invalid_api_request": True,
        }
        if not os.path.exists(self.config_path):
            with open(self.config_path, "w", encoding="utf-8") as handle:
                json.dump(defaults, handle, indent=2)
        with open(self.config_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        self.session.timeout_enabled = bool(data.get("timeout_enabled", True))
        self.session.timeout_minutes = int(data.get("timeout_minutes", 15))
        self.session.reset_on_read = bool(data.get("reset_on_read", True))
        self.session.lock_on_invalid_api_request = bool(data.get("lock_on_invalid_api_request", True))

    def _save_config(self):
        data = {
            "timeout_enabled": self.session.timeout_enabled,
            "timeout_minutes": self.session.timeout_minutes,
            "reset_on_read": self.session.reset_on_read,
            "lock_on_invalid_api_request": self.session.lock_on_invalid_api_request,
        }
        with open(self.config_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)

    def _database_status(self) -> dict:
        if not self.storage.file_exists():
            return {
                "state": "missing",
                "exists": False,
                "initialized": False,
                "message": "Database file is missing. Initialize a new database to begin.",
            }
        if self.storage.file_is_empty():
            return {
                "state": "uninitialized",
                "exists": True,
                "initialized": False,
                "message": "Database file exists but is empty. Initialize it or reset it to replace the file.",
            }
        try:
            if not self.storage.has_schema():
                return {
                    "state": "uninitialized",
                    "exists": True,
                    "initialized": False,
                    "message": "Database file exists but is not initialized. Initialize it or reset it from the UI.",
                }
            verifier = self.storage.get_meta("passphrase_verifier")
        except sqlite3.DatabaseError:
            return {
                "state": "corrupted",
                "exists": True,
                "initialized": False,
                "message": "Database is unreadable or corrupted. Replace or recreate the database file.",
            }
        if not verifier:
            return {
                "state": "uninitialized",
                "exists": True,
                "initialized": False,
                "message": "Database exists but has no passphrase configured. Initialize it or reset it from the UI.",
            }
        if self.session.is_unlocked():
            message = "Database is unlocked and ready."
        elif self.session.database_notice:
            message = self.session.database_notice
        else:
            message = "Database is ready. Unlock it with the current passphrase, or reset it to replace stored data."
        return {
            "state": "ready",
            "exists": True,
            "initialized": True,
            "message": message,
        }

    def _require_database_ready(self):
        info = self._database_status()
        if info["state"] != "ready":
            raise StorageError(info["message"])

    def _validate_passphrase(self, value: str, *, label: str = "Passphrase"):
        if not value or not value.strip():
            raise ValidationError(f"{label} is required.")

    def _synchronize_session_with_database(self, database: dict) -> dict:
        if database["state"] == "ready":
            return database
        if self.session.is_unlocked():
            self.session.lock("Database became unavailable. Service locked.", level="warning")
        return database

    def status(self) -> dict:
        database = self._synchronize_session_with_database(self._database_status())
        unlocked = self.session.is_unlocked()
        return {
            "locked": not unlocked,
            "unlocked": unlocked,
            "timeout_enabled": self.session.timeout_enabled,
            "timeout_minutes": self.session.timeout_minutes,
            "reset_on_read": self.session.reset_on_read,
            "lock_on_invalid_api_request": self.session.lock_on_invalid_api_request,
            "seconds_remaining": self.session.seconds_remaining(),
            "last_event": self.session.last_event,
            "database_state": database["state"],
            "database_message": database["message"],
            "database_exists": database["exists"],
            "database_initialized": database["initialized"],
            "database_ready": database["state"] == "ready",
            "database_unlockable": database["state"] == "ready",
            "database_can_initialize": database["state"] in {"missing", "empty", "uninitialized"},
            "database_can_reset": database["exists"],
            "database_needs_setup": database["state"] in {"missing", "uninitialized"},
        }

    def unlock(
        self,
        passphrase: str,
        *,
        remote_addr: str = "",
        method: str = "",
        path: str = "",
        status: int | None = None,
        query_string: str = "",
        user_agent: str = "",
    ) -> tuple[bool, str]:
        if not passphrase:
            self.session.log(
                "Unlock failure: empty passphrase.",
                level="warning",
                remote_addr=remote_addr,
                method=method,
                path=path,
                status=status,
                query_string=query_string,
                user_agent=user_agent,
            )
            return False, "Passphrase is required."

        database = self._database_status()
        if database["state"] != "ready":
            self.session.log(
                f'Unlock failure: {database["message"]}',
                level="warning",
                remote_addr=remote_addr,
                method=method,
                path=path,
                status=status,
                query_string=query_string,
                user_agent=user_agent,
            )
            return False, database["message"]

        try:
            verifier = self.storage.get_meta("passphrase_verifier")
            if decrypt_value(verifier, passphrase) != VERIFY_TEXT:
                raise ValueError("invalid passphrase")
        except Exception:
            self.session.log(
                "Unlock failure: incorrect passphrase.",
                level="warning",
                remote_addr=remote_addr,
                method=method,
                path=path,
                status=status,
                query_string=query_string,
                user_agent=user_agent,
            )
            return False, "Incorrect passphrase for the existing database."

        self.session.unlock(
            passphrase,
            "Service unlocked.",
            remote_addr=remote_addr,
            method=method,
            path=path,
            status=status,
            query_string=query_string,
            user_agent=user_agent,
        )
        return True, "Service unlocked."

    def lock(
        self,
        *,
        remote_addr: str = "",
        method: str = "",
        path: str = "",
        status: int | None = None,
        query_string: str = "",
        user_agent: str = "",
    ):
        if self.session.unlocked_passphrase is None:
            self.session.log(
                "Lock requested while already locked.",
                level="warning",
                remote_addr=remote_addr,
                method=method,
                path=path,
                status=status,
                query_string=query_string,
                user_agent=user_agent,
            )
            return False
        self.session.lock(
            "Service locked.",
            level="info",
            remote_addr=remote_addr,
            method=method,
            path=path,
            status=status,
            query_string=query_string,
            user_agent=user_agent,
        )
        return True

    def initialize_database(self, passphrase: str):
        self._validate_passphrase(passphrase, label="Initial passphrase")
        database = self._database_status()
        if database["state"] == "ready":
            raise ValidationError("Database is already initialized.")
        if database["state"] == "corrupted":
            raise StorageError(database["message"])
        self.storage.initialize()
        self.storage.set_meta("passphrase_verifier", encrypt_value(VERIFY_TEXT, passphrase.strip()))
        self.session.set_database_notice("Database created successfully. Unlock it with the new passphrase.")
        self.session.lock("Database initialized. Unlock it to continue.", level="success")

    def reset_database(self, new_passphrase: str, confirmation: str):
        self._validate_passphrase(new_passphrase, label="New passphrase")
        database = self._database_status()
        if not database["exists"]:
            raise ValidationError("No existing database file was found to reset.")
        if confirmation.strip() != "RESET":
            raise ValidationError('Type RESET to confirm database replacement.')
        self.storage.reset()
        self.storage.initialize()
        self.storage.set_meta("passphrase_verifier", encrypt_value(VERIFY_TEXT, new_passphrase.strip()))
        self.session.set_database_notice("Database reset successfully. Unlock it with the new passphrase.")
        self.session.lock("Database reset. Unlock it with the new passphrase to continue.", level="warning")

    def change_passphrase(self, current_passphrase: str, new_passphrase: str):
        self._require_database_ready()
        self._require_unlocked()
        self._validate_passphrase(current_passphrase, label="Current passphrase")
        self._validate_passphrase(new_passphrase, label="New passphrase")
        try:
            verifier = self.storage.get_meta("passphrase_verifier")
            if decrypt_value(verifier, current_passphrase) != VERIFY_TEXT:
                raise ValueError("invalid passphrase")
        except Exception:
            raise ValidationError("Current passphrase is incorrect.") from None

        payloads = self.storage.list_all_secret_payloads()
        try:
            for item in payloads:
                plaintext = decrypt_value(item["value_encrypted"], current_passphrase)
                rotated = encrypt_value(plaintext, new_passphrase.strip())
                self.storage.replace_secret_payload(item["vault_name"], item["secret_name"], rotated)
        except KeyError:
            raise StorageError("A secret changed during passphrase rotation. Try again.") from None
        self.storage.set_meta("passphrase_verifier", encrypt_value(VERIFY_TEXT, new_passphrase.strip()))
        self.session.unlock(new_passphrase.strip(), "Passphrase changed.")

    def configure_session(self, *, timeout_enabled: bool, timeout_minutes: int, reset_on_read: bool, lock_on_invalid_api_request: bool):
        if timeout_minutes < 1:
            raise ValidationError("Timeout must be at least 1 minute.")
        self.session.configure(
            timeout_enabled=timeout_enabled,
            timeout_minutes=timeout_minutes,
            reset_on_read=reset_on_read,
            lock_on_invalid_api_request=lock_on_invalid_api_request,
        )
        self._save_config()

    def _require_unlocked(self) -> str:
        self._require_database_ready()
        self.session.apply_timeout()
        if not self.session.is_unlocked() or self.session.unlocked_passphrase is None:
            raise LockedError("Service is locked.")
        return self.session.unlocked_passphrase

    def _validate_name(self, value: str, label: str):
        if not value or not value.strip():
            raise ValidationError(f"{label} is required.")

    def _vault_exists(self, vault_name: str) -> bool:
        try:
            return any(item["name"] == vault_name.strip() for item in self.storage.list_vaults())
        except sqlite3.DatabaseError:
            return False

    def list_vaults(self) -> list[dict]:
        try:
            self._require_database_ready()
            return self.storage.list_vaults()
        except (StorageError, sqlite3.DatabaseError):
            return []

    def create_vault(self, name: str):
        self._require_unlocked()
        self._validate_name(name, "Vault name")
        try:
            self.storage.create_vault(name.strip())
        except sqlite3.IntegrityError:
            raise ValidationError("Vault already exists.") from None
        self.session.log("Vault created.")

    def rename_vault(self, current_name: str, new_name: str):
        self._require_unlocked()
        self._validate_name(current_name, "Current vault name")
        self._validate_name(new_name, "New vault name")
        try:
            self.storage.rename_vault(current_name.strip(), new_name.strip())
        except KeyError:
            raise NotFoundError("Vault not found.") from None
        except sqlite3.IntegrityError:
            raise ValidationError("A vault with that name already exists.") from None
        self.session.log("Vault renamed.")

    def delete_vault(self, name: str):
        self._require_unlocked()
        self._validate_name(name, "Vault name")
        try:
            self.storage.delete_vault(name.strip())
        except KeyError:
            raise NotFoundError("Vault not found.") from None
        self.session.log("Vault deleted.")

    def list_secrets(self, vault_name: str) -> list[dict]:
        if not vault_name:
            return []
        try:
            return self.storage.list_secrets(vault_name.strip())
        except (KeyError, sqlite3.DatabaseError, json.JSONDecodeError):
            return []

    def _load_secret_record(self, vault_name: str, name: str) -> dict:
        try:
            return self.storage.get_secret(vault_name.strip(), name.strip())
        except KeyError:
            if not self._vault_exists(vault_name):
                raise NotFoundError("Vault not found.") from None
            raise NotFoundError("Secret not found.") from None
        except (sqlite3.DatabaseError, json.JSONDecodeError):
            raise StorageError("Database is unreadable or corrupted. Replace or recreate the database file.") from None

    def create_secret(self, vault_name: str, name: str, value: str, metadata: dict | None = None):
        passphrase = self._require_unlocked()
        self._validate_name(vault_name, "Vault name")
        self._validate_name(name, "Secret name")
        metadata = metadata or {}
        encrypted = encrypt_value(value, passphrase)
        try:
            self.storage.create_secret(vault_name.strip(), name.strip(), encrypted, metadata)
        except KeyError:
            raise NotFoundError("Vault not found.") from None
        except sqlite3.IntegrityError:
            raise ValidationError("Secret already exists in this vault.") from None
        self.session.log("Secret created.")

    def rename_secret(self, vault_name: str, current_name: str, new_name: str):
        self._require_unlocked()
        self._validate_name(new_name, "New secret name")
        try:
            self.storage.update_secret(vault_name.strip(), current_name.strip(), new_name=new_name.strip())
        except KeyError:
            raise NotFoundError("Secret not found.") from None
        except sqlite3.IntegrityError:
            raise ValidationError("A secret with that name already exists in this vault.") from None
        self.session.log("Secret renamed.")

    def update_secret_value(self, vault_name: str, name: str, value: str):
        passphrase = self._require_unlocked()
        encrypted = encrypt_value(value, passphrase)
        try:
            self.storage.update_secret(vault_name.strip(), name.strip(), value_encrypted=encrypted)
        except KeyError:
            raise NotFoundError("Secret not found.") from None
        self.session.log("Secret updated.")

    def delete_secret(self, vault_name: str, name: str):
        self._require_unlocked()
        try:
            self.storage.delete_secret(vault_name.strip(), name.strip())
        except KeyError:
            raise NotFoundError("Secret not found.") from None
        self.session.log("Secret deleted.")

    def add_or_update_metadata(self, vault_name: str, secret_name: str, key: str, value: str):
        self._require_unlocked()
        self._validate_name(key, "Metadata key")
        current = self._load_secret_record(vault_name, secret_name)
        metadata = current["metadata"]
        metadata[key.strip()] = value
        self.storage.update_secret(vault_name.strip(), secret_name.strip(), metadata=metadata)
        self.session.log("Metadata saved.")

    def get_metadata_value(self, vault_name: str, secret_name: str, key: str):
        self._require_unlocked()
        self._validate_name(key, "Metadata key")
        current = self._load_secret_record(vault_name, secret_name)
        return current["metadata"].get(key.strip())

    def delete_metadata(self, vault_name: str, secret_name: str, key: str):
        self._require_unlocked()
        current = self._load_secret_record(vault_name, secret_name)
        metadata = current["metadata"]
        if key not in metadata:
            raise NotFoundError("Metadata key not found.")
        metadata.pop(key, None)
        self.storage.update_secret(vault_name.strip(), secret_name.strip(), metadata=metadata)
        self.session.log("Metadata deleted.")

    def read_secret(self, vault_name: str, name: str, *, log_event: bool = True) -> dict:
        passphrase = self._require_unlocked()
        record = self._load_secret_record(vault_name, name)
        try:
            value = decrypt_value(record["value_encrypted"], passphrase)
        except Exception:
            raise StorageError("Secret decryption failed. Verify the passphrase or recreate the database.") from None
        try:
            self.storage.touch_secret(vault_name.strip(), name.strip())
        except KeyError:
            raise NotFoundError("Secret not found.") from None
        if log_event:
            self.session.log(f'Secret read: "{vault_name.strip()}/{name.strip()}".', level="success")
        if self.session.reset_on_read:
            self.session.touch()
        refreshed = self._load_secret_record(vault_name, name)
        return {
            "vault": vault_name.strip(),
            "name": refreshed["name"],
            "value": value,
            "metadata": refreshed["metadata"],
            "created_at": refreshed["created_at"],
            "updated_at": refreshed["updated_at"],
            "last_accessed_at": refreshed["last_accessed_at"],
        }

    def _metadata_payload(self, secret: dict) -> dict:
        payload = {
            "created_at": secret["created_at"],
            "updated_at": secret["updated_at"],
            "last_accessed_at": secret["last_accessed_at"],
        }
        payload.update(secret["metadata"])
        return payload

    def read_metadata(self, vault_name: str, name: str, *, log_event: bool = True) -> dict:
        secret = self.read_secret(vault_name, name, log_event=log_event)
        return self._metadata_payload(secret)

    def read_metadata_field(self, vault_name: str, name: str, field: str, *, log_event: bool = True):
        payload = self.read_metadata(vault_name, name, log_event=log_event)
        if field in payload:
            return payload[field]
        raise NotFoundError("Metadata field not found.")

    def session_events(self) -> list[dict]:
        return [entry.as_dict() for entry in self.session.events]

    def audit_api_request(
        self,
        *,
        level: str,
        message: str,
        remote_addr: str,
        method: str,
        path: str,
        status: int,
        query_string: str = "",
        user_agent: str = "",
    ):
        self.session.log(
            message,
            level=level,
            remote_addr=remote_addr,
            method=method,
            path=path,
            status=status,
            query_string=query_string,
            user_agent=user_agent,
        )

    def handle_invalid_api_request(
        self,
        *,
        message: str,
        remote_addr: str,
        method: str,
        path: str,
        status: int,
        query_string: str = "",
        user_agent: str = "",
    ) -> bool:
        self.audit_api_request(
            level="security",
            message=message,
            remote_addr=remote_addr,
            method=method,
            path=path,
            status=status,
            query_string=query_string,
            user_agent=user_agent,
        )
        if self.session.lock_on_invalid_api_request and self.session.unlocked_passphrase is not None:
            self.session.lock("Auto-lock triggered after invalid API request.", level="security")
            return True
        return False

    def build_retrieval_helper(self, vault_name: str, secret_name: str, metadata_key: str = "", *, mode: str = "secret") -> dict:
        def helper_payload(*, api_path: str, python_snippet: str, curl_snippet: str, selection_label: str, kind: str) -> dict:
            return {
                "api_path": api_path,
                "python_snippet": python_snippet,
                "curl_snippet": curl_snippet,
                "selection_label": selection_label,
                "kind": kind,
            }

        if not vault_name:
            return helper_payload(
                api_path="",
                python_snippet="",
                curl_snippet="",
                selection_label="No vault selected.",
                kind="none",
            )
        if not secret_name:
            return helper_payload(
                api_path="",
                python_snippet="",
                curl_snippet="",
                selection_label=f'Vault "{vault_name}" selected. Pick a secret to generate helper code.',
                kind="vault",
            )

        api_secret_path = f"/api/v1/vaults/{quote(vault_name)}/secrets/{quote(secret_name)}"
        if metadata_key:
            system_field_map = {
                "created_at": "created_at",
                "updated_at": "updated_at",
                "last_accessed_at": "last_accessed_at",
            }
            try:
                record = self.storage.get_secret(vault_name, secret_name)
            except Exception:
                return helper_payload(
                    api_path="",
                    python_snippet="",
                    curl_snippet="",
                    selection_label="Selected metadata field is unavailable.",
                    kind="missing",
                )
            if metadata_key in system_field_map or metadata_key in record["metadata"]:
                field_label = metadata_key
            else:
                return helper_payload(
                    api_path="",
                    python_snippet="",
                    curl_snippet="",
                    selection_label=f'Metadata field "{metadata_key}" is no longer available.',
                    kind="missing",
                )
            api_path = f"{api_secret_path}/metadata/{quote(metadata_key)}"
            python_snippet = (
                "import requests\n\n"
                f'response = requests.get("http://127.0.0.1:5000{api_path}")\n'
                "response.raise_for_status()\n"
                "field_value = response.json()\n"
                "print(field_value)"
            )
            curl_snippet = f'curl -fsS "http://127.0.0.1:5000{api_path}"'
            return helper_payload(
                api_path=api_path,
                python_snippet=python_snippet,
                curl_snippet=curl_snippet,
                selection_label=f'Metadata field "{field_label}" from "{vault_name}/{secret_name}".',
                kind="metadata-field",
            )

        if mode == "metadata":
            api_path = f"{api_secret_path}/metadata"
            python_snippet = (
                "import requests\n\n"
                f'response = requests.get("http://127.0.0.1:5000{api_path}")\n'
                "response.raise_for_status()\n"
                "metadata = response.json()\n"
                "print(metadata)"
            )
            curl_snippet = f'curl -fsS "http://127.0.0.1:5000{api_path}"'
            return helper_payload(
                api_path=api_path,
                python_snippet=python_snippet,
                curl_snippet=curl_snippet,
                selection_label=f'All metadata for "{vault_name}/{secret_name}".',
                kind="metadata-collection",
            )

        python_snippet = (
            "import requests\n\n"
            f'response = requests.get("http://127.0.0.1:5000{api_secret_path}")\n'
            "response.raise_for_status()\n"
            'print(response.json()["value"])'
        )
        curl_snippet = f'curl -fsS "http://127.0.0.1:5000{api_secret_path}"'
        return helper_payload(
            api_path=api_secret_path,
            python_snippet=python_snippet,
            curl_snippet=curl_snippet,
            selection_label=f'Secret "{vault_name}/{secret_name}".',
            kind="secret",
        )
