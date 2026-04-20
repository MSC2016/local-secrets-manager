"""Local read-only API routes for secrets and metadata.

These endpoints expose status, secret values, and metadata from the currently
unlocked local vault. They are intentionally scoped for local use and rely on
the in-process service/session state managed by ``SecretsService``.
"""

from flask import Blueprint, current_app, has_request_context, jsonify, request

from app.models import LockedError, NotFoundError, StorageError

# All API routes are grouped under /api/v1 to keep browser UI and programmatic
# read endpoints separated.
api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


def get_service():
    """Return the shared service instance stored on the Flask app config."""
    return current_app.config["service"]


def _request_details() -> dict:
    """Collect normalized request metadata for audit logging.

    Returns empty strings when called outside a request context so helper
    functions remain safe to use from tests or non-request code paths.
    """
    if not has_request_context():
        return {
            "remote_addr": "",
            "method": "",
            "path": "",
            "query_string": "",
            "user_agent": "",
        }
    return {
        "remote_addr": request.remote_addr or "",
        "method": request.method,
        "path": request.path,
        "query_string": request.query_string.decode("utf-8", errors="ignore"),
        "user_agent": request.user_agent.string or "",
    }


def _log_api(level: str, message: str, status: int):
    """Write a normal API audit entry for the current request."""
    get_service().audit_api_request(level=level, message=message, status=status, **_request_details())


def _handle_invalid_api_request(message: str, status: int):
    """Handle malformed or invalid API requests through the service layer.

    This centralizes the behavior that may optionally auto-lock the service
    after invalid API activity, depending on current session settings.
    """
    get_service().handle_invalid_api_request(message=message, status=status, **_request_details())


@api_bp.get("/status")
def status():
    payload = get_service().status()
    _log_api("info", "status request succeeded", 200)
    return jsonify(payload)


@api_bp.get("/vaults/<vault>/secrets/<secret>")
def get_secret(vault: str, secret: str):
    try:
        payload = get_service().read_secret(vault, secret, log_event=False)
        _log_api("success", "secret read succeeded", 200)
        return jsonify({"value": payload["value"]})
    except LockedError as exc:
        _log_api("warning", "request denied because service is locked", 423)
        return jsonify({"error": str(exc)}), 423
    except StorageError as exc:
        _log_api("error", "request failed because storage is unavailable", 503)
        return jsonify({"error": str(exc)}), 503
    except NotFoundError as exc:
        invalid_message = "invalid vault request" if str(exc) == "Vault not found." else "invalid secret request"
        _handle_invalid_api_request(invalid_message, 404)
        return jsonify({"error": str(exc)}), 404


@api_bp.get("/vaults/<vault>/secrets/<secret>/metadata")
def get_metadata(vault: str, secret: str):
    try:
        payload = get_service().read_metadata(vault, secret, log_event=False)
        _log_api("success", "metadata read succeeded", 200)
        return jsonify(payload)
    except LockedError as exc:
        _log_api("warning", "request denied because service is locked", 423)
        return jsonify({"error": str(exc)}), 423
    except StorageError as exc:
        _log_api("error", "request failed because storage is unavailable", 503)
        return jsonify({"error": str(exc)}), 503
    except NotFoundError as exc:
        invalid_message = "invalid vault request" if str(exc) == "Vault not found." else "invalid metadata request"
        _handle_invalid_api_request(invalid_message, 404)
        return jsonify({"error": str(exc)}), 404


@api_bp.get("/vaults/<vault>/secrets/<secret>/metadata/<field>")
def get_metadata_field(vault: str, secret: str, field: str):
    try:
        payload = get_service().read_metadata_field(vault, secret, field, log_event=False)
        _log_api("success", "metadata field read succeeded", 200)
        return jsonify(payload)
    except LockedError as exc:
        _log_api("warning", "request denied because service is locked", 423)
        return jsonify({"error": str(exc)}), 423
    except StorageError as exc:
        _log_api("error", "request failed because storage is unavailable", 503)
        return jsonify({"error": str(exc)}), 503
    except NotFoundError as exc:
        invalid_message = "invalid vault request" if str(exc) == "Vault not found." else "invalid metadata field request"
        _handle_invalid_api_request(invalid_message, 404)
        return jsonify({"error": str(exc)}), 404


@api_bp.errorhandler(400)
def handle_bad_request(exc):
    _handle_invalid_api_request("malformed API request", 400)
    return jsonify({"error": "Malformed API request."}), 400


@api_bp.errorhandler(405)
def handle_method_not_allowed(exc):
    _handle_invalid_api_request("invalid API method", 405)
    return jsonify({"error": "Method not allowed."}), 405


@api_bp.route("/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def handle_unknown_api_path(subpath: str):
    _handle_invalid_api_request("invalid API path", 404)
    return jsonify({"error": "API path not found."}), 404
