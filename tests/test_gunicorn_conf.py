import importlib
import logging
import sys
from types import SimpleNamespace


def _load_gunicorn_conf(monkeypatch, **env):
    for key in ["APP_HOST", "APP_PORT", "GUNICORN_WORKERS", "GUNICORN_THREADS", "GUNICORN_TIMEOUT", "GUNICORN_GRACEFUL_TIMEOUT"]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    sys.modules.pop("gunicorn_conf", None)
    return importlib.import_module("gunicorn_conf")


def test_gunicorn_defaults_to_single_worker(monkeypatch):
    module = _load_gunicorn_conf(monkeypatch)

    assert module.bind == "0.0.0.0:5000"
    assert module.workers == 1
    assert module.threads == 4
    assert module.timeout == 60
    assert module.graceful_timeout == 30


def test_gunicorn_respects_host_port_and_thread_overrides(monkeypatch):
    module = _load_gunicorn_conf(
        monkeypatch,
        APP_HOST="127.0.0.1",
        APP_PORT="9000",
        GUNICORN_WORKERS="3",
        GUNICORN_THREADS="8",
        GUNICORN_TIMEOUT="120",
        GUNICORN_GRACEFUL_TIMEOUT="45",
    )

    assert module.bind == "127.0.0.1:9000"
    assert module.workers == 3
    assert module.threads == 8
    assert module.timeout == 120
    assert module.graceful_timeout == 45


def test_gunicorn_warns_when_running_multiple_workers(monkeypatch, caplog):
    module = _load_gunicorn_conf(monkeypatch)
    server = SimpleNamespace(cfg=SimpleNamespace(workers=2))

    with caplog.at_level(logging.WARNING, logger="gunicorn.error"):
        module.when_ready(server)

    assert "multi-worker mode can behave inconsistently" in caplog.text
