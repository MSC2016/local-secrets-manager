from app.models import StorageError
from tests.conftest import create_sample_secret


def _latest_log(app):
    return app.config["service"].session_events()[0]


def test_api_status_endpoint_reports_locked_state(client):
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["locked"] is True
    assert payload["unlocked"] is False
    assert payload["database_state"] == "missing"


def test_api_requires_unlocked_state(client):
    client.post("/database/initialize", data={"passphrase": "passphrase", "confirm_passphrase": "passphrase"})
    response = client.get("/api/v1/vaults/dev/secrets/api-key")
    assert response.status_code == 423
    assert response.get_json()["error"] == "Service is locked."


def test_api_secret_and_metadata_endpoints_success(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    create_sample_secret(service)

    secret_response = client.get(
        "/api/v1/vaults/dev/secrets/api-key",
        environ_overrides={"REMOTE_ADDR": "192.168.1.218"},
    )
    assert secret_response.status_code == 200
    secret_payload = secret_response.get_json()
    assert secret_payload == {"value": "secret-value"}
    assert "vault" not in secret_payload
    assert "name" not in secret_payload
    assert "metadata" not in secret_payload
    assert "created_at" not in secret_payload
    assert "updated_at" not in secret_payload
    assert "last_accessed_at" not in secret_payload
    secret_log = _latest_log(app)
    assert secret_log["level"] == "success"
    assert secret_log["method"] == "GET"
    assert secret_log["path"] == "/api/v1/vaults/dev/secrets/api-key"
    assert secret_log["status"] == 200
    assert secret_log["message"] == "secret read succeeded"
    assert secret_log["remote_addr"] == "192.168.1.218"

    metadata_response = client.get("/api/v1/vaults/dev/secrets/api-key/metadata")
    assert metadata_response.status_code == 200
    metadata_payload = metadata_response.get_json()
    assert metadata_payload["env"] == "test"
    assert metadata_payload["owner"] == "me"
    assert isinstance(metadata_payload["created_at"], str)
    assert isinstance(metadata_payload["updated_at"], str)
    assert "value" not in metadata_payload
    assert "vault" not in metadata_payload
    assert "name" not in metadata_payload
    assert "metadata" not in metadata_payload


def test_api_metadata_collection_without_custom_metadata_returns_only_system_fields(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {})

    response = client.get("/api/v1/vaults/dev/secrets/api-key/metadata")

    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload) == {"created_at", "updated_at", "last_accessed_at"}
    assert "vault" not in payload
    assert "name" not in payload
    assert "value" not in payload
    assert "metadata" not in payload


def test_api_metadata_returns_storage_error_instead_of_crashing(client, app, monkeypatch):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    create_sample_secret(service)
    monkeypatch.setattr(
        service,
        "read_metadata",
        lambda vault, secret, **kwargs: (_ for _ in ()).throw(StorageError("metadata storage failed")),
    )

    response = client.get("/api/v1/vaults/dev/secrets/api-key/metadata")
    assert response.status_code == 503
    assert response.get_json()["error"] == "metadata storage failed"


def test_api_returns_not_found_for_missing_secret(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")

    response = client.get("/api/v1/vaults/dev/secrets/missing")
    assert response.status_code == 404
    assert response.get_json()["error"] == "Secret not found."
    assert service.status()["locked"] is True
    latest = _latest_log(app)
    previous = app.config["service"].session_events()[1]
    assert latest["message"] == "Auto-lock triggered after invalid API request."
    assert latest["level"] == "security"
    assert previous["message"] == "invalid secret request"
    assert previous["path"] == "/api/v1/vaults/dev/secrets/missing"
    assert previous["status"] == 404


def test_api_returns_not_found_for_missing_vault_and_logs_security_event(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")

    response = client.get("/api/v1/vaults/missing/secrets/api-key")
    assert response.status_code == 404
    assert response.get_json()["error"] == "Vault not found."
    invalid_entry = app.config["service"].session_events()[1]
    assert invalid_entry["message"] == "invalid vault request"
    assert invalid_entry["path"] == "/api/v1/vaults/missing/secrets/api-key"


def test_api_metadata_requires_unlocked_state(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    create_sample_secret(service)
    service.lock()

    response = client.get("/api/v1/vaults/dev/secrets/api-key/metadata")
    assert response.status_code == 423
    assert response.get_json()["error"] == "Service is locked."
    latest = _latest_log(app)
    assert latest["level"] == "warning"
    assert latest["message"] == "request denied because service is locked"
    assert latest["path"] == "/api/v1/vaults/dev/secrets/api-key/metadata"


def test_api_metadata_returns_not_found_for_missing_secret(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")

    response = client.get("/api/v1/vaults/dev/secrets/missing/metadata")
    assert response.status_code == 404
    assert response.get_json()["error"] == "Secret not found."


def test_api_metadata_field_success(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    create_sample_secret(service)

    # Test system field
    response = client.get("/api/v1/vaults/dev/secrets/api-key/metadata/created_at")
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, str)  # created_at is a string

    # Test custom metadata field
    response = client.get("/api/v1/vaults/dev/secrets/api-key/metadata/env")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload == "test"


def test_api_secret_endpoint_returns_only_secret_value_payload(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    create_sample_secret(service)

    response = client.get("/api/v1/vaults/dev/secrets/api-key")

    assert response.status_code == 200
    assert response.get_json() == {"value": "secret-value"}


def test_api_metadata_field_returns_not_found_for_missing_field(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    create_sample_secret(service)

    response = client.get("/api/v1/vaults/dev/secrets/api-key/metadata/missing_field")
    assert response.status_code == 404
    assert response.get_json()["error"] == "Metadata field not found."


def test_api_metadata_field_returns_not_found_for_missing_secret(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")

    response = client.get("/api/v1/vaults/dev/secrets/missing/metadata/created_at")
    assert response.status_code == 404
    assert response.get_json()["error"] == "Secret not found."


def test_api_metadata_field_requires_unlocked_state(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    create_sample_secret(service)
    service.lock()

    response = client.get("/api/v1/vaults/dev/secrets/api-key/metadata/created_at")
    assert response.status_code == 423
    assert response.get_json()["error"] == "Service is locked."


def test_invalid_api_request_does_not_lock_when_option_disabled(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.configure_session(
        timeout_enabled=True,
        timeout_minutes=15,
        reset_on_read=True,
        lock_on_invalid_api_request=False,
    )

    response = client.get("/api/v1/vaults/dev/secrets/missing")
    assert response.status_code == 404
    assert service.status()["locked"] is False
    latest = _latest_log(app)
    assert latest["message"] == "invalid secret request"
    assert latest["level"] == "security"


def test_api_request_logging_falls_back_to_blank_remote_addr_when_missing(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")

    response = client.get(
        "/api/v1/status",
        environ_overrides={"REMOTE_ADDR": ""},
    )

    assert response.status_code == 200
    latest = _latest_log(app)
    assert latest["message"] == "status request succeeded"
    assert latest["remote_addr"] == ""


def test_api_returns_storage_error_for_corrupted_database(client, temp_paths):
    (temp_paths / "secrets.db").write_bytes(b"bad-db")
    response = client.get("/api/v1/vaults/dev/secrets/api-key")
    assert response.status_code == 503
    assert "unreadable or corrupted" in response.get_json()["error"]


def test_api_metadata_returns_storage_error_for_corrupted_database(client, temp_paths):
    (temp_paths / "secrets.db").write_bytes(b"bad-db")
    response = client.get("/api/v1/vaults/dev/secrets/api-key/metadata")
    assert response.status_code == 503
    assert "unreadable or corrupted" in response.get_json()["error"]
