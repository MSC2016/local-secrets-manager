import os
from logging import getLogger


LOGGER = getLogger("gunicorn.error")


def _env_int(name: str, default: int) -> int:
    return max(int(os.environ.get(name, str(default))), 1)


host = os.environ.get("APP_HOST", "0.0.0.0")
port = os.environ.get("APP_PORT", "5000")

bind = f"{host}:{port}"
# This app keeps unlock state, timeout state, and the runtime log in memory, so
# a single worker is the safest default for predictable local behavior.
workers = _env_int("GUNICORN_WORKERS", 1)
threads = _env_int("GUNICORN_THREADS", 4)
timeout = _env_int("GUNICORN_TIMEOUT", 60)
graceful_timeout = _env_int("GUNICORN_GRACEFUL_TIMEOUT", 30)
accesslog = "-"
errorlog = "-"


def when_ready(server):
    if server.cfg.workers > 1:
        LOGGER.warning(
            "Gunicorn is running with %s workers. Local Secrets Manager stores unlock "
            "state, timeout state, and runtime log in each worker process, so "
            "multi-worker mode can behave inconsistently.",
            server.cfg.workers,
        )
