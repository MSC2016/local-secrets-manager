"""Legacy filename kept temporarily; behavior tests now live in split modules."""
import json
from datetime import timedelta

import pytest

from app.models import LockedError, NotFoundError, StorageError, ValidationError
from app.service import SecretsService
from app.session import now_utc
from tests.conftest import create_sample_secret


def test_service_starts_locked_with_missing_database(service):
    status = service.status()
    assert status["locked"] is True
    assert status["database_state"] == "missing"
    assert status["database_ready"] is False
    assert status["seconds_remaining"] == 0


def test_initialize_database_creates_valid_locked_state(service):
    service.initialize_database("passphrase")

    status = service.status()
    assert status["database_state"] == "ready"
    assert status["locked"] is True
    assert status["database_message"] == "Database created successfully. Unlock it with the new passphrase."
    assert service.storage.get_meta("passphrase_verifier") is not None
    assert "Database initialized." in service.session.last_event


def test_initialize_database_rejects_blank_passphrase(service):
    with pytest.raises(ValidationError, match="Initial passphrase is required"):
        service.initialize_database("   ")


def test_initialize_database_rejects_existing_initialized_db(unlocked_service):
    with pytest.raises(ValidationError, match="already initialized"):
        unlocked_service.initialize_database("new-passphrase")


def test_unlock_requires_initialized_database(service):
    ok, message = service.unlock("passphrase")

    assert ok is False
    assert message == "Database file is missing. Initialize a new database to begin."


def test_unlock_success_and_failure_paths(service):
    service.initialize_database("passphrase")

    ok, message = service.unlock("wrong")
    assert ok is False
    assert message == "Incorrect passphrase for the existing database."

    ok, message = service.unlock("passphrase")
    assert ok is True
    assert message == "Service unlocked."
    assert service.status()["unlocked"] is True
    assert service.status()["lock_on_invalid_api_request"] is True


def test_status_locks_service_when_database_file_disappears(temp_paths):
    service = SecretsService(
        db_path=str(temp_paths / "secrets.db"),
        config_path=str(temp_paths / "config.json"),
    )
    service.initialize_database("passphrase")
    ok, message = service.unlock("passphrase")
    assert ok is True, message

    (temp_paths / "secrets.db").unlink()

    status = service.status()
    assert status["database_state"] == "missing"
    assert status["database_ready"] is False
    assert status["database_unlockable"] is False
    assert status["locked"] is True
    assert status["unlocked"] is False
    assert status["database_message"] == "Database file is missing. Initialize a new database to begin."
    assert "Database became unavailable. Service locked." in service.session.last_event


def test_unlock_persists_across_service_instances_with_initialized_db(temp_paths):
    first = SecretsService(
        db_path=str(temp_paths / "secrets.db"),
        config_path=str(temp_paths / "config.json"),
    )
    first.initialize_database("passphrase")
    ok, _ = first.unlock("passphrase")
    assert ok is True
    first.create_vault("dev")
    first.create_secret("dev", "api-key", "secret-value", {"env": "dev"})
    first.lock()

    second = SecretsService(
        db_path=str(temp_paths / "secrets.db"),
        config_path=str(temp_paths / "config.json"),
    )
    ok, message = second.unlock("passphrase")
    assert ok is True
    assert message == "Service unlocked."
    assert second.read_secret("dev", "api-key")["value"] == "secret-value"


def test_session_state_is_process_local_across_service_instances(temp_paths):
    first = SecretsService(
        db_path=str(temp_paths / "secrets.db"),
        config_path=str(temp_paths / "config.json"),
    )
    first.initialize_database("passphrase")
    ok, message = first.unlock("passphrase")
    assert ok is True, message
    assert first.status()["unlocked"] is True

    second = SecretsService(
        db_path=str(temp_paths / "secrets.db"),
        config_path=str(temp_paths / "config.json"),
    )

    status = second.status()
    assert status["locked"] is True
    assert status["unlocked"] is False
    assert status["database_state"] == "ready"
    assert "Service started in locked state." in second.session.last_event
    assert not any("Service unlocked." in entry.rendered() for entry in second.session.events)


def test_change_passphrase_reencrypts_existing_secrets_and_updates_session(unlocked_service):
    create_sample_secret(unlocked_service)

    unlocked_service.change_passphrase("passphrase", "rotated")
    unlocked_service.lock()

    ok, wrong_message = unlocked_service.unlock("passphrase")
    assert ok is False
    assert wrong_message == "Incorrect passphrase for the existing database."

    ok, message = unlocked_service.unlock("rotated")
    assert ok is True
    assert message == "Service unlocked."
    assert unlocked_service.read_secret("dev", "api-key")["value"] == "secret-value"
    assert any("Passphrase changed." in entry.rendered() for entry in unlocked_service.session.events)


def test_change_passphrase_requires_unlocked_state_and_correct_current_passphrase(service):
    service.initialize_database("passphrase")

    with pytest.raises(LockedError, match="Service is locked"):
        service.change_passphrase("passphrase", "rotated")

    ok, _ = service.unlock("passphrase")
    assert ok is True

    with pytest.raises(ValidationError, match="Current passphrase is incorrect"):
        service.change_passphrase("wrong", "rotated")


def test_change_passphrase_rejects_blank_new_value(unlocked_service):
    with pytest.raises(ValidationError, match="New passphrase is required"):
        unlocked_service.change_passphrase("passphrase", "  ")


def test_initialize_database_when_empty_file_exists(service, temp_paths):
    (temp_paths / "secrets.db").touch()

    service.initialize_database("passphrase")

    assert service.status()["database_state"] == "ready"


def test_reset_existing_database_replaces_existing_content_and_passphrase(unlocked_service):
    create_sample_secret(unlocked_service)
    unlocked_service.lock()

    unlocked_service.reset_database("fresh-passphrase", "RESET")

    status = unlocked_service.status()
    assert status["database_state"] == "ready"
    assert status["locked"] is True
    assert status["database_message"] == "Database reset successfully. Unlock it with the new passphrase."
    assert unlocked_service.list_vaults() == []
    assert "Database reset. Unlock it with the new passphrase to continue." in unlocked_service.session.last_event

    ok, message = unlocked_service.unlock("passphrase")
    assert ok is False
    assert message == "Incorrect passphrase for the existing database."

    ok, message = unlocked_service.unlock("fresh-passphrase")
    assert ok is True, message
    assert unlocked_service.list_vaults() == []


def test_database_message_transitions_from_initialize_notice_to_unlocked_ready(service):
    service.initialize_database("passphrase")
    assert service.status()["database_message"] == "Database created successfully. Unlock it with the new passphrase."

    ok, message = service.unlock("passphrase")
    assert ok is True, message
    assert service.status()["database_message"] == "Database is unlocked and ready."


def test_database_message_transitions_from_reset_notice_to_generic_ready_after_unlock_and_lock(unlocked_service):
    unlocked_service.reset_database("fresh-passphrase", "RESET")
    assert unlocked_service.status()["database_message"] == "Database reset successfully. Unlock it with the new passphrase."

    ok, message = unlocked_service.unlock("fresh-passphrase")
    assert ok is True, message
    assert unlocked_service.status()["database_message"] == "Database is unlocked and ready."

    unlocked_service.lock()
    assert unlocked_service.status()["database_message"] == "Database is ready. Unlock it with the current passphrase, or reset it to replace stored data."


def test_database_state_and_message_stay_consistent_for_ready_paths(service):
    service.initialize_database("passphrase")
    status = service.status()
    assert status["database_state"] == "ready"
    assert "new passphrase" in status["database_message"]

    ok, message = service.unlock("passphrase")
    assert ok is True, message
    status = service.status()
    assert status["database_state"] == "ready"
    assert status["database_message"] == "Database is unlocked and ready."


def test_reset_database_requires_existing_file_and_confirmation(service):
    with pytest.raises(ValidationError, match="No existing database file"):
        service.reset_database("fresh-passphrase", "RESET")

    service.initialize_database("passphrase")
    with pytest.raises(ValidationError, match="Type RESET"):
        service.reset_database("fresh-passphrase", "WRONG")


def test_reset_database_recovers_from_corrupted_file(temp_paths):
    db_path = temp_paths / "secrets.db"
    db_path.write_bytes(b"not-a-sqlite-db")
    service = SecretsService(
        db_path=str(db_path),
        config_path=str(temp_paths / "config.json"),
    )

    service.reset_database("fresh-passphrase", "RESET")

    ok, message = service.unlock("fresh-passphrase")
    assert ok is True, message
    assert service.list_vaults() == []


def test_service_creates_default_config_if_missing(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    service = SecretsService(
        db_path=str(data_dir / "secrets.db"),
        config_path=str(data_dir / "config.json"),
    )

    assert (data_dir / "config.json").exists()
    assert service.status()["timeout_minutes"] == 15
    assert service.status()["lock_on_invalid_api_request"] is True


def test_corrupted_database_reports_unhealthy_state(temp_paths):
    db_path = temp_paths / "secrets.db"
    db_path.write_bytes(b"not-a-sqlite-db")
    service = SecretsService(
        db_path=str(db_path),
        config_path=str(temp_paths / "config.json"),
    )

    status = service.status()
    assert status["database_state"] == "corrupted"
    assert "unreadable or corrupted" in status["database_message"]

    ok, message = service.unlock("passphrase")
    assert ok is False
    assert "unreadable or corrupted" in message


def test_locked_service_rejects_management_actions(service):
    service.initialize_database("passphrase")
    with pytest.raises(LockedError):
        service.create_vault("dev")
    with pytest.raises(LockedError):
        service.create_secret("dev", "name", "value", {})
    with pytest.raises(LockedError):
        service.read_secret("dev", "name")


def test_lock_when_already_locked_is_safe(service):
    service.initialize_database("passphrase")
    result = service.lock()
    assert result is False
    assert "already locked" in service.session.last_event


def test_create_vault_requires_non_blank_name(unlocked_service):
    with pytest.raises(ValidationError, match="Vault name is required"):
        unlocked_service.create_vault("   ")


def test_duplicate_vault_create_raises_validation(unlocked_service):
    unlocked_service.create_vault("dev")
    with pytest.raises(ValidationError, match="Vault already exists"):
        unlocked_service.create_vault("dev")


def test_rename_vault_behaviors(unlocked_service):
    unlocked_service.create_vault("dev")
    unlocked_service.create_vault("prod")

    unlocked_service.rename_vault("dev", "dev-renamed")
    names = [vault["name"] for vault in unlocked_service.list_vaults()]
    assert "dev-renamed" in names
    assert "dev" not in names

    with pytest.raises(NotFoundError, match="Vault not found"):
        unlocked_service.rename_vault("missing", "x")

    with pytest.raises(ValidationError, match="already exists"):
        unlocked_service.rename_vault("dev-renamed", "prod")


def test_delete_vault_behaviors(unlocked_service):
    unlocked_service.create_vault("dev")
    unlocked_service.delete_vault("dev")
    assert "dev" not in [vault["name"] for vault in unlocked_service.list_vaults()]

    with pytest.raises(NotFoundError, match="Vault not found"):
        unlocked_service.delete_vault("dev")


def test_create_secret_and_read_secret_behavior(unlocked_service):
    create_sample_secret(unlocked_service)

    record = unlocked_service.read_secret("dev", "api-key")

    assert record["vault"] == "dev"
    assert record["name"] == "api-key"
    assert record["value"] == "secret-value"
    assert record["metadata"] == {"env": "test", "owner": "me"}
    assert record["last_accessed_at"] is not None


def test_create_secret_requires_existing_vault(unlocked_service):
    with pytest.raises(NotFoundError, match="Vault not found"):
        unlocked_service.create_secret("missing", "api-key", "secret", {})


def test_create_secret_requires_non_blank_name(unlocked_service):
    unlocked_service.create_vault("dev")
    with pytest.raises(ValidationError, match="Secret name is required"):
        unlocked_service.create_secret("dev", "   ", "secret", {})


def test_duplicate_secret_create_raises_validation(unlocked_service):
    create_sample_secret(unlocked_service)
    with pytest.raises(ValidationError, match="Secret already exists"):
        unlocked_service.create_secret("dev", "api-key", "other", {})


def test_rename_secret_behaviors(unlocked_service):
    create_sample_secret(unlocked_service)
    unlocked_service.create_secret("dev", "another", "value", {})

    unlocked_service.rename_secret("dev", "api-key", "api-key-renamed")
    names = [item["name"] for item in unlocked_service.list_secrets("dev")]
    assert "api-key-renamed" in names
    assert "api-key" not in names

    with pytest.raises(NotFoundError, match="Secret not found"):
        unlocked_service.rename_secret("dev", "missing", "x")

    with pytest.raises(ValidationError, match="already exists"):
        unlocked_service.rename_secret("dev", "api-key-renamed", "another")


def test_update_secret_value_changes_only_value(unlocked_service):
    create_sample_secret(unlocked_service)
    before = unlocked_service.storage.get_secret("dev", "api-key")

    unlocked_service.update_secret_value("dev", "api-key", "new-secret-value")

    after = unlocked_service.read_secret("dev", "api-key")
    assert after["value"] == "new-secret-value"
    assert after["metadata"] == {"env": "test", "owner": "me"}
    assert after["updated_at"] >= before["updated_at"]


def test_update_secret_missing_raises_not_found(unlocked_service):
    unlocked_service.create_vault("dev")
    with pytest.raises(NotFoundError, match="Secret not found"):
        unlocked_service.update_secret_value("dev", "missing", "value")


def test_delete_secret_behaviors(unlocked_service):
    create_sample_secret(unlocked_service)
    unlocked_service.delete_secret("dev", "api-key")
    assert unlocked_service.list_secrets("dev") == []

    with pytest.raises(NotFoundError, match="Secret not found"):
        unlocked_service.delete_secret("dev", "api-key")


def test_list_secrets_unknown_or_blank_vault_returns_empty_list(unlocked_service):
    unlocked_service.create_vault("dev")
    assert unlocked_service.list_secrets("") == []
    assert unlocked_service.list_secrets("missing") == []


def test_metadata_lifecycle(unlocked_service):
    create_sample_secret(unlocked_service)

    unlocked_service.add_or_update_metadata("dev", "api-key", "team", "platform")
    updated = unlocked_service.read_secret("dev", "api-key")
    assert updated["metadata"]["team"] == "platform"

    unlocked_service.add_or_update_metadata("dev", "api-key", "team", "infra")
    updated = unlocked_service.read_secret("dev", "api-key")
    assert updated["metadata"]["team"] == "infra"

    unlocked_service.delete_metadata("dev", "api-key", "team")
    updated = unlocked_service.read_secret("dev", "api-key")
    assert "team" not in updated["metadata"]


def test_get_metadata_value_reports_existing_and_missing_keys(unlocked_service):
    create_sample_secret(unlocked_service)

    assert unlocked_service.get_metadata_value("dev", "api-key", "owner") == "me"
    assert unlocked_service.get_metadata_value("dev", "api-key", "team") is None


def test_metadata_requires_valid_key_and_secret(unlocked_service):
    create_sample_secret(unlocked_service)

    with pytest.raises(ValidationError, match="Metadata key is required"):
        unlocked_service.add_or_update_metadata("dev", "api-key", "  ", "value")

    with pytest.raises(NotFoundError, match="Secret not found"):
        unlocked_service.add_or_update_metadata("dev", "missing", "env", "dev")

    with pytest.raises(NotFoundError, match="Secret not found"):
        unlocked_service.delete_metadata("dev", "missing", "env")


def test_delete_missing_metadata_key_raises_not_found(unlocked_service):
    create_sample_secret(unlocked_service)
    with pytest.raises(NotFoundError, match="Metadata key not found"):
        unlocked_service.delete_metadata("dev", "api-key", "not-there")


def test_read_secret_reports_missing_if_touch_finds_no_row(unlocked_service, monkeypatch):
    create_sample_secret(unlocked_service)
    monkeypatch.setattr(unlocked_service.storage, "touch_secret", lambda vault, name: (_ for _ in ()).throw(KeyError(name)))

    with pytest.raises(NotFoundError, match="Secret not found"):
        unlocked_service.read_secret("dev", "api-key")


def test_change_passphrase_reports_storage_issue_if_secret_disappears(unlocked_service, monkeypatch):
    create_sample_secret(unlocked_service)
    monkeypatch.setattr(
        unlocked_service.storage,
        "replace_secret_payload",
        lambda vault, name, value: (_ for _ in ()).throw(KeyError(name)),
    )

    with pytest.raises(StorageError, match="changed during passphrase rotation"):
        unlocked_service.change_passphrase("passphrase", "rotated")


def test_read_metadata_reports_corrupted_metadata_as_storage_error(unlocked_service, monkeypatch):
    create_sample_secret(unlocked_service)
    monkeypatch.setattr(
        unlocked_service.storage,
        "get_secret",
        lambda vault, name: (_ for _ in ()).throw(json.JSONDecodeError("bad", "{}", 0)),
    )

    with pytest.raises(StorageError, match="unreadable or corrupted"):
        unlocked_service.read_metadata("dev", "api-key")


def test_read_metadata_returns_only_metadata_fields(unlocked_service):
    create_sample_secret(unlocked_service)
    result = unlocked_service.read_metadata("dev", "api-key")
    assert set(result) == {"created_at", "updated_at", "last_accessed_at", "env", "owner"}
    assert "value" not in result
    assert "vault" not in result
    assert "name" not in result
    assert "metadata" not in result
    assert result["env"] == "test"
    assert result["owner"] == "me"


def test_read_metadata_without_custom_metadata_returns_only_system_fields(unlocked_service):
    unlocked_service.create_vault("dev")
    unlocked_service.create_secret("dev", "api-key", "secret-value", {})

    result = unlocked_service.read_metadata("dev", "api-key")

    assert set(result) == {"created_at", "updated_at", "last_accessed_at"}
    assert "metadata" not in result
    assert "vault" not in result
    assert "name" not in result
    assert "value" not in result


def test_read_metadata_field_system_fields(unlocked_service):
    create_sample_secret(unlocked_service)
    result = unlocked_service.read_metadata_field("dev", "api-key", "created_at")
    assert isinstance(result, str)
    result = unlocked_service.read_metadata_field("dev", "api-key", "updated_at")
    assert isinstance(result, str)
    result = unlocked_service.read_metadata_field("dev", "api-key", "last_accessed_at")
    assert result is None or isinstance(result, str)


def test_read_metadata_field_custom_fields(unlocked_service):
    create_sample_secret(unlocked_service)
    result = unlocked_service.read_metadata_field("dev", "api-key", "env")
    assert result == "test"
    result = unlocked_service.read_metadata_field("dev", "api-key", "owner")
    assert result == "me"


def test_read_metadata_field_missing_field_raises_not_found(unlocked_service):
    create_sample_secret(unlocked_service)
    with pytest.raises(NotFoundError, match="Metadata field not found"):
        unlocked_service.read_metadata_field("dev", "api-key", "missing")


def test_read_metadata_field_missing_secret_raises_not_found(unlocked_service):
    unlocked_service.create_vault("dev")
    with pytest.raises(NotFoundError, match="Secret not found"):
        unlocked_service.read_metadata_field("dev", "missing", "created_at")


def test_retrieval_helper_generation(unlocked_service):
    create_sample_secret(unlocked_service)

    none_helper = unlocked_service.build_retrieval_helper("", "")
    assert none_helper["kind"] == "none"

    vault_helper = unlocked_service.build_retrieval_helper("dev", "")
    assert vault_helper["kind"] == "vault"

    secret_helper = unlocked_service.build_retrieval_helper("dev", "api-key")
    assert secret_helper["kind"] == "secret"
    assert secret_helper["api_path"] == "/api/v1/vaults/dev/secrets/api-key"
    assert 'print(response.json()["value"])' in secret_helper["python_snippet"]
    assert 'curl -fsS "http://127.0.0.1:5000/api/v1/vaults/dev/secrets/api-key"' in secret_helper["curl_snippet"]
    assert "| python -c" not in secret_helper["curl_snippet"]

    metadata_helper = unlocked_service.build_retrieval_helper("dev", "api-key", "env")
    assert metadata_helper["kind"] == "metadata-field"
    assert metadata_helper["api_path"] == "/api/v1/vaults/dev/secrets/api-key/metadata/env"
    assert "field_value = response.json()" in metadata_helper["python_snippet"]
    assert "print(field_value)" in metadata_helper["python_snippet"]
    assert 'curl -fsS "http://127.0.0.1:5000/api/v1/vaults/dev/secrets/api-key/metadata/env"' in metadata_helper["curl_snippet"]
    assert "| python -c" not in metadata_helper["curl_snippet"]

    metadata_collection_helper = unlocked_service.build_retrieval_helper("dev", "api-key", mode="metadata")
    assert metadata_collection_helper["kind"] == "metadata-collection"
    assert "metadata = response.json()" in metadata_collection_helper["python_snippet"]
    assert "print(metadata)" in metadata_collection_helper["python_snippet"]
    assert 'payload["metadata"]' not in metadata_collection_helper["python_snippet"]
    assert "| python -c" not in metadata_collection_helper["curl_snippet"]

    system_metadata_helper = unlocked_service.build_retrieval_helper("dev", "api-key", "created_at")
    assert system_metadata_helper["kind"] == "metadata-field"
    assert system_metadata_helper["api_path"] == "/api/v1/vaults/dev/secrets/api-key/metadata/created_at"
    assert "field_value = response.json()" in system_metadata_helper["python_snippet"]
    assert "print(field_value)" in system_metadata_helper["python_snippet"]

    missing_helper = unlocked_service.build_retrieval_helper("dev", "api-key", "missing")
    assert missing_helper["kind"] == "missing"


def test_read_secret_resets_timer_when_enabled(unlocked_service):
    create_sample_secret(unlocked_service)
    unlocked_service.session.timeout_minutes = 10
    unlocked_service.session.last_activity_at = now_utc() - timedelta(minutes=5)

    before = unlocked_service.session.seconds_remaining()
    unlocked_service.read_secret("dev", "api-key")
    after = unlocked_service.session.seconds_remaining()

    assert before < after


def test_read_secret_does_not_reset_timer_when_disabled(unlocked_service):
    create_sample_secret(unlocked_service)
    unlocked_service.session.timeout_minutes = 10
    unlocked_service.session.reset_on_read = False
    unlocked_service.session.last_activity_at = now_utc() - timedelta(minutes=5)

    before = unlocked_service.session.seconds_remaining()
    unlocked_service.read_secret("dev", "api-key")
    after = unlocked_service.session.seconds_remaining()

    assert abs(after - before) <= 1


def test_auto_lock_triggers_when_timer_expires(unlocked_service):
    unlocked_service.session.timeout_enabled = True
    unlocked_service.session.timeout_minutes = 1
    unlocked_service.session.last_activity_at = now_utc() - timedelta(minutes=2)

    status = unlocked_service.status()

    assert status["locked"] is True
    assert "Auto-lock triggered after inactivity." in unlocked_service.session.last_event


def test_timer_can_be_disabled(unlocked_service):
    unlocked_service.configure_session(timeout_enabled=False, timeout_minutes=5, reset_on_read=False, lock_on_invalid_api_request=True)
    status = unlocked_service.status()
    assert status["timeout_enabled"] is False
    assert status["seconds_remaining"] is None


def test_configuring_session_resets_timer_to_new_timeout(unlocked_service):
    unlocked_service.session.timeout_enabled = True
    unlocked_service.session.timeout_minutes = 30
    unlocked_service.session.last_activity_at = now_utc() - timedelta(minutes=10)

    unlocked_service.configure_session(timeout_enabled=True, timeout_minutes=1, reset_on_read=True, lock_on_invalid_api_request=True)
    status = unlocked_service.status()

    assert status["locked"] is False
    assert status["timeout_minutes"] == 1
    assert status["seconds_remaining"] in {59, 60}


def test_configuring_session_does_not_instantly_lock_when_timeout_is_lowered(unlocked_service):
    unlocked_service.session.timeout_enabled = True
    unlocked_service.session.timeout_minutes = 30
    unlocked_service.session.last_activity_at = now_utc() - timedelta(minutes=10)

    unlocked_service.configure_session(timeout_enabled=True, timeout_minutes=1, reset_on_read=False, lock_on_invalid_api_request=False)

    assert unlocked_service.status()["locked"] is False
    assert "Session settings saved." in unlocked_service.session.last_event
    assert unlocked_service.status()["lock_on_invalid_api_request"] is False


def test_invalid_timeout_configuration_raises_and_does_not_change_state(unlocked_service):
    original = unlocked_service.status()
    with pytest.raises(ValidationError, match="at least 1 minute"):
        unlocked_service.configure_session(timeout_enabled=True, timeout_minutes=0, reset_on_read=True, lock_on_invalid_api_request=True)
    assert unlocked_service.status()["timeout_minutes"] == original["timeout_minutes"]


def test_runtime_log_survives_lock_unlock_cycles_while_service_is_running(unlocked_service):
    unlocked_service.session.log("before-cycle")
    unlocked_service.lock()
    ok, message = unlocked_service.unlock("passphrase")
    assert ok is True, message

    messages = [entry.message for entry in unlocked_service.session.events]
    assert "before-cycle" in messages
    assert "Service locked." in messages
    assert "Service unlocked." in messages


def test_runtime_log_resets_when_service_restarts(temp_paths):
    first = SecretsService(
        db_path=str(temp_paths / "secrets.db"),
        config_path=str(temp_paths / "config.json"),
    )
    first.initialize_database("passphrase")
    first.session.log("runtime-only event")

    second = SecretsService(
        db_path=str(temp_paths / "secrets.db"),
        config_path=str(temp_paths / "config.json"),
    )

    messages = [entry.message for entry in second.session.events]
    assert "runtime-only event" not in messages
    assert messages == ["Service started in locked state."]


def test_runtime_log_keeps_full_history_for_service_lifetime(unlocked_service):
    for index in range(120):
        unlocked_service.session.log(f"event-{index}")
    assert len(unlocked_service.session.events) >= 121
    assert unlocked_service.session.events[0].message == "event-119"
