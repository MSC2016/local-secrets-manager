import json
import os
import shutil
import tempfile

import coverage

_BEHAVE_COVERAGE = coverage.Coverage(config_file=True)
_BEHAVE_COVERAGE.start()

from app.main import create_app
from app.service import SecretsService


DEFAULT_CONFIG = {
    "timeout_enabled": True,
    "timeout_minutes": 15,
    "reset_on_read": True,
    "lock_on_invalid_api_request": True,
}


def before_all(context):
    context._original_app_data_dir = os.environ.get("APP_DATA_DIR")
    context._original_timeout_watcher = SecretsService._start_timeout_watcher
    SecretsService._start_timeout_watcher = lambda self: None
    context._coverage = _BEHAVE_COVERAGE


def before_scenario(context, scenario):
    context.tmpdir = tempfile.mkdtemp(prefix="behave-secrets-")
    context.data_dir = os.path.join(context.tmpdir, "data")
    os.makedirs(context.data_dir, exist_ok=True)
    with open(os.path.join(context.data_dir, "config.json"), "w", encoding="utf-8") as handle:
        json.dump(DEFAULT_CONFIG, handle, indent=2)

    os.environ["APP_DATA_DIR"] = context.data_dir
    context.app = create_app()
    context.client = context.app.test_client()
    context.service = context.app.config["service"]
    context.response = None
    context.json = None
    context.page_text = ""
    context.last_event = ""
    context.merged_status = ""
    context.status_panel_open = False


def after_scenario(context, scenario):
    shutil.rmtree(context.tmpdir, ignore_errors=True)


def after_all(context):
    context._coverage.stop()
    context._coverage.save()
    context._coverage.report(show_missing=True)
    context._coverage.html_report()
    SecretsService._start_timeout_watcher = context._original_timeout_watcher
    if context._original_app_data_dir is None:
        os.environ.pop("APP_DATA_DIR", None)
    else:
        os.environ["APP_DATA_DIR"] = context._original_app_data_dir
