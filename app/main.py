import os

from flask import Flask

from app.api import api_bp
from app.service import SecretsService
from app.web import web_bp


def create_app() -> Flask:
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.environ.get("APP_DATA_DIR", os.path.join(root_dir, "data"))
    db_path = os.path.join(data_dir, "secrets.db")
    config_path = os.path.join(data_dir, "config.json")

    app = Flask(__name__, template_folder="templates")
    app.config["service"] = SecretsService(db_path=db_path, config_path=config_path)
    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp)
    return app
