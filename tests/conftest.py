import json

import pytest

from app.main import create_app
from app.service import SecretsService


DEFAULT_CONFIG = {
    "timeout_enabled": True,
    "timeout_minutes": 15,
    "reset_on_read": True,
    "lock_on_invalid_api_request": True,
}


@pytest.fixture(autouse=True)
def disable_timeout_thread(monkeypatch):
    monkeypatch.setattr(SecretsService, "_start_timeout_watcher", lambda self: None)


@pytest.fixture
def temp_paths(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config_path = data_dir / "config.json"
    config_path.write_text(json.dumps(DEFAULT_CONFIG), encoding="utf-8")
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    return data_dir


@pytest.fixture
def service(temp_paths):
    return SecretsService(
        db_path=str(temp_paths / "secrets.db"),
        config_path=str(temp_paths / "config.json"),
    )


@pytest.fixture
def unlocked_service(service):
    service.initialize_database("passphrase")
    ok, message = service.unlock("passphrase")
    assert ok is True, message
    return service


@pytest.fixture
def app(temp_paths):
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


def create_sample_secret(service):
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "test", "owner": "me"})
