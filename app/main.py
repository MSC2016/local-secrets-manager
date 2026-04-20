"""Flask application factory for the Local Secrets Manager.

This module builds the Flask app, wires the service layer into app config,
and registers the web and API blueprints.

Environment variables:
    APP_DATA_DIR: Override the directory that stores secrets.db and config.json.
"""

import os

from flask import Flask

from app.api import api_bp
from app.service import SecretsService
from app.web import web_bp


def create_app() -> Flask:
    """Create and configure the Flask application.

    Returns:
        Flask: Configured Flask app instance with the service layer attached.

    Notes:
        The service instance is stored in ``app.config["service"]`` so both
        blueprints can access the same in-process runtime/session state.
    """
    # Resolve the project root so the default local data directory works
    # both in development and when the app is launched from different cwd values.
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Allow overriding the storage location from the environment.
    data_dir = os.environ.get("APP_DATA_DIR", os.path.join(root_dir, "data"))
    
    # Keep database content and runtime/session configuration in the same data dir.
    db_path = os.path.join(data_dir, "secrets.db")
    config_path = os.path.join(data_dir, "config.json")

    app = Flask(__name__, template_folder="templates")

    # Attach the service layer once so requests share the same application-level
    # service instance inside this process.
    app.config["service"] = SecretsService(db_path=db_path, config_path=config_path)

    # Register browser UI routes and local API routes.
    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp)
    return app
