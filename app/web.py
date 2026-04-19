import json

from flask import Blueprint, current_app, has_request_context, jsonify, redirect, render_template, request, url_for

from app.models import LockedError, NotFoundError, StorageError, ValidationError
from app.web_support import (
    build_home_url,
    coerce_expanded_list,
    current_panel_state,
    expanded_values_from_request,
    merged_expanded_list,
    merged_status_text,
    request_log_details,
)


web_bp = Blueprint("web", __name__)


def get_service():
    return current_app.config["service"]


def redirect_home(
    *,
    vault: str | None = None,
    secret: str | None = None,
    expanded: str | list[str] | tuple[str, ...] | None = None,
    field: str | None = None,
    target: str | None = None,
    panel: str | None = None,
    vault_action: str | None = None,
    create_secret: bool = False,
    editor_secret: str | None = None,
    editor_mode: str | None = None,
    pending_metadata_key: str | None = None,
    pending_metadata_value: str | None = None,
    pending_metadata_existing_value: str | None = None,
):
    params = {}
    if vault:
        params["vault"] = vault
    if secret:
        params["secret"] = secret
    expanded_values = coerce_expanded_list(expanded)
    if expanded_values:
        params["expanded"] = expanded_values
    if field:
        params["field"] = field
    if target:
        params["target"] = target
    if panel:
        params["panel"] = panel
    if vault_action:
        params["vault_action"] = vault_action
    if create_secret:
        params["create_secret"] = "1"
    if editor_secret:
        params["editor_secret"] = editor_secret
    if editor_mode:
        params["editor_mode"] = editor_mode
    if pending_metadata_key:
        params["pending_metadata_key"] = pending_metadata_key
    if pending_metadata_value is not None:
        params["pending_metadata_value"] = pending_metadata_value
    if pending_metadata_existing_value is not None:
        params["pending_metadata_existing_value"] = pending_metadata_existing_value
    return redirect(url_for("web.home", **params))




def redirect_with_feedback(
    message: str,
    *,
    vault: str | None = None,
    secret: str | None = None,
    expanded: str | list[str] | tuple[str, ...] | None = None,
    field: str | None = None,
    target: str | None = None,
    panel: str | None = None,
    vault_action: str | None = None,
    create_secret: bool = False,
    editor_secret: str | None = None,
    editor_mode: str | None = None,
    pending_metadata_key: str | None = None,
    pending_metadata_value: str | None = None,
    pending_metadata_existing_value: str | None = None,
):
    get_service().session.log(message, **request_log_details())
    return redirect_home(
        vault=vault,
        secret=secret,
        expanded=expanded,
        field=field,
        target=target,
        panel=panel,
        vault_action=vault_action,
        create_secret=create_secret,
        editor_secret=editor_secret,
        editor_mode=editor_mode,
        pending_metadata_key=pending_metadata_key,
        pending_metadata_value=pending_metadata_value,
        pending_metadata_existing_value=pending_metadata_existing_value,
    )


def parse_metadata_input(raw_text: str) -> dict:
    raw_text = raw_text.strip()
    if not raw_text:
        return {}
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Metadata must be valid JSON: {exc.msg}.") from None
    if not isinstance(parsed, dict):
        raise ValidationError("Metadata must be a JSON object.")
    return parsed


def validate_confirmed_passphrase(passphrase: str, confirmation: str):
    if passphrase.strip() != confirmation.strip():
        raise ValidationError("Passphrases do not match.")


def normalize_selection_state(service, vaults: list[dict], *, locked_or_unready: bool) -> dict:
    valid_names = [vault["name"] for vault in vaults]
    selected_vault = request.args.get("vault", "").strip()
    secret_name = request.args.get("secret", "").strip()
    expanded_secret_names = coerce_expanded_list(request.args.getlist("expanded"))
    field_name = request.args.get("field", "").strip()
    selected_target = request.args.get("target", "secret").strip().lower()
    # Backward compatibility: if field is present but target is not, infer metadata-field
    if "field" in request.args and "target" not in request.args:
        selected_target = "metadata-field"

    search_query = request.args.get("q", "").strip()
    vault_action = request.args.get("vault_action", "").strip().lower()
    create_secret = request.args.get("create_secret", "").strip().lower() in {"1", "true", "yes", "on"}
    editor_secret = request.args.get("editor_secret", "").strip()
    editor_mode = request.args.get("editor_mode", "").strip().lower()
    pending_metadata_key = request.args.get("pending_metadata_key", "").strip()
    pending_metadata_value = request.args.get("pending_metadata_value", "")
    pending_metadata_existing_value = request.args.get("pending_metadata_existing_value", "")

    if selected_vault:
        if selected_vault not in valid_names:
            selected_vault = valid_names[0] if valid_names else ""
    elif len(valid_names) == 1:
        selected_vault = valid_names[0]
    else:
        selected_vault = ""

    secrets = [] if locked_or_unready or not selected_vault else service.list_secrets(selected_vault)
    if search_query:
        lowered = search_query.lower()
        secrets = [item for item in secrets if lowered in item["name"].lower()]

    selected_secret = next((item for item in secrets if item["name"] == secret_name), None)
    if selected_secret is None:
        secret_name = ""
        expanded_secret_names = []
        field_name = ""
        selected_target = "secret"
    else:
        valid_field_names = {"created_at", "updated_at", "last_accessed_at", *selected_secret["metadata"].keys()}
        if selected_target not in {"secret", "metadata", "metadata-field"}:
            selected_target = "secret"
        if field_name and field_name not in valid_field_names:
            field_name = ""
        if selected_target == "metadata-field" and not field_name:
            selected_target = "secret"
        elif selected_target != "metadata-field":
            field_name = ""
        if selected_target in {"metadata", "metadata-field"}:
            expanded_secret_names = merged_expanded_list(expanded_secret_names, secret_name)

    helper_mode = "secret"
    if selected_target == "metadata-field" and field_name:
        helper_mode = "metadata-field"
    elif selected_target == "metadata" and selected_secret is not None:
        helper_mode = "metadata"

    if vault_action not in {"create", "rename"}:
        vault_action = ""
    if vault_action == "rename" and not selected_vault:
        vault_action = ""

    if not has_request_context() or not selected_vault:
        create_secret = False

    valid_secret_names = {item["name"] for item in secrets}
    if editor_mode not in {"rename", "value", "metadata"}:
        editor_mode = ""
    if not editor_secret or editor_secret not in valid_secret_names or editor_secret not in expanded_secret_names:
        editor_secret = ""
        editor_mode = ""
    elif not editor_mode:
        editor_secret = ""

    if editor_mode != "metadata" or editor_secret != secret_name or not pending_metadata_key:
        pending_metadata_key = ""
        pending_metadata_value = ""
        pending_metadata_existing_value = ""

    metadata_overwrite = None
    if pending_metadata_key:
        metadata_overwrite = {
            "key": pending_metadata_key,
            "new_value": pending_metadata_value,
            "existing_value": pending_metadata_existing_value,
        }

    return {
        "selected_vault": selected_vault,
        "secrets": secrets,
        "selected_secret": selected_secret,
        "secret_name": secret_name,
        "expanded_secret": secret_name if secret_name in expanded_secret_names else "",
        "expanded_secrets": expanded_secret_names,
        "selected_field": field_name,
        "selected_target": selected_target,
        "search_query": search_query,
        "helper_mode": helper_mode,
        "vault_action": vault_action,
        "create_secret": create_secret,
        "editor_secret": editor_secret,
        "editor_mode": editor_mode,
        "metadata_overwrite": metadata_overwrite,
    }


@web_bp.get("/")
def home():
    service = get_service()
    status = service.status()
    panel = request.args.get("panel", "").strip().lower()
    locked_or_unready = status["locked"] or not status["database_ready"]
    vaults = [] if locked_or_unready else service.list_vaults()
    selection = normalize_selection_state(service, vaults, locked_or_unready=locked_or_unready)
    helper = service.build_retrieval_helper(
        selection["selected_vault"],
        selection["secret_name"],
        selection["selected_field"],
        mode=selection["helper_mode"],
    )
    session_log = service.session_events()
    log_filter_search = request.args.get("log_q", "").strip()
    requested_log_levels = [level for level in request.args.getlist("log_level") if level in {"info", "success", "warning", "error", "security"}]
    active_log_levels = requested_log_levels or ["info", "success", "warning", "error", "security"]
    lowered_log_search = log_filter_search.lower()
    filtered_session_log = [
        entry
        for entry in session_log
        if entry["level"] in active_log_levels and (not lowered_log_search or lowered_log_search in entry["search_text"])
    ]

    def home_url(**overrides):
        params = {
            "vault": selection["selected_vault"],
            "secret": selection["secret_name"],
            "expanded": selection["expanded_secrets"],
            "field": selection["selected_field"],
            "target": selection["selected_target"],
            "q": selection["search_query"],
            "vault_action": selection["vault_action"],
            "create_secret": "1" if selection["create_secret"] else "",
            "editor_secret": selection["editor_secret"],
            "editor_mode": selection["editor_mode"],
            "pending_metadata_key": selection["metadata_overwrite"]["key"] if selection["metadata_overwrite"] else "",
            "pending_metadata_value": selection["metadata_overwrite"]["new_value"] if selection["metadata_overwrite"] else "",
            "pending_metadata_existing_value": selection["metadata_overwrite"]["existing_value"] if selection["metadata_overwrite"] else "",
        }
        params.update(overrides)
        return build_home_url(**params)

    def toggle_secret_expansion_url(secret_name: str) -> str:
        expanded = [name for name in selection["expanded_secrets"] if name != secret_name]
        if secret_name not in selection["expanded_secrets"]:
            expanded.append(secret_name)
        return home_url(secret=secret_name, expanded=expanded, field="", target="secret")

    return render_template(
        "index.html",
        status=status,
        merged_status=merged_status_text(status),
        top_panel_open=panel == "expanded",
        vaults=vaults,
        selected_vault=selection["selected_vault"],
        secrets=selection["secrets"],
        selected_secret=selection["selected_secret"],
        expanded_secret=selection["expanded_secret"],
        expanded_secrets=selection["expanded_secrets"],
        selected_field=selection["selected_field"],
        selected_target=selection["selected_target"],
        search_query=selection["search_query"],
        helper=helper,
        home_url=home_url,
        toggle_secret_expansion_url=toggle_secret_expansion_url,
        vault_action=selection["vault_action"],
        create_secret=selection["create_secret"],
        editor_secret=selection["editor_secret"],
        editor_mode=selection["editor_mode"],
        metadata_overwrite=selection["metadata_overwrite"],
        session_log=session_log,
        filtered_session_log=filtered_session_log,
        log_filter_search=log_filter_search,
        log_filter_levels=active_log_levels,
    )


@web_bp.post("/database/initialize")
def initialize_database():
    try:
        passphrase = request.form.get("passphrase", "")
        validate_confirmed_passphrase(passphrase, request.form.get("confirm_passphrase", ""))
        get_service().initialize_database(passphrase)
        return redirect_home(panel=current_panel_state())
    except (ValidationError, StorageError) as exc:
        return redirect_with_feedback(str(exc), panel=current_panel_state())


@web_bp.post("/database/change-passphrase")
def change_passphrase():
    try:
        new_passphrase = request.form.get("new_passphrase", "")
        validate_confirmed_passphrase(new_passphrase, request.form.get("confirm_passphrase", ""))
        get_service().change_passphrase(
            request.form.get("current_passphrase", ""),
            new_passphrase,
        )
        return redirect_home(panel=current_panel_state())
    except (LockedError, ValidationError, StorageError) as exc:
        return redirect_with_feedback(str(exc), panel=current_panel_state())


@web_bp.post("/database/reset")
def reset_database():
    try:
        new_passphrase = request.form.get("new_passphrase", "")
        validate_confirmed_passphrase(new_passphrase, request.form.get("confirm_passphrase", ""))
        get_service().reset_database(
            new_passphrase,
            request.form.get("confirmation", ""),
        )
        return redirect_home(panel=current_panel_state())
    except (ValidationError, StorageError) as exc:
        return redirect_with_feedback(str(exc), panel=current_panel_state())


@web_bp.post("/unlock")
def unlock():
    success, message = get_service().unlock(request.form.get("passphrase", ""), **request_log_details())
    if success:
        return redirect_home(panel=current_panel_state())
    return redirect_with_feedback(f"Unlock failed: {message}", panel=current_panel_state())


@web_bp.post("/lock")
def lock():
    was_locked = not get_service().lock(**request_log_details())
    if was_locked:
        return redirect_with_feedback("Service is already locked.", panel=current_panel_state())
    return redirect_home(panel=current_panel_state())


@web_bp.post("/settings")
def settings():
    try:
        get_service().configure_session(
            timeout_enabled=request.form.get("timeout_enabled") == "on",
            timeout_minutes=int(request.form.get("timeout_minutes", "15")),
            reset_on_read=request.form.get("reset_on_read") == "on",
            lock_on_invalid_api_request=request.form.get("lock_on_invalid_api_request") == "on",
        )
        return redirect_home(
            vault=request.form.get("selected_vault", ""),
            secret=request.form.get("selected_secret", ""),
            expanded=expanded_values_from_request(request.form),
            field=request.form.get("selected_field", ""),
            target=request.form.get("selected_target", ""),
            panel=current_panel_state(),
        )
    except (ValueError, ValidationError) as exc:
        return redirect_with_feedback(str(exc), panel=current_panel_state())


@web_bp.post("/vaults/create")
def create_vault():
    name = request.form.get("name", "")
    try:
        get_service().create_vault(name)
        return redirect_home(vault=name.strip())
    except (LockedError, ValidationError, NotFoundError, StorageError) as exc:
        return redirect_with_feedback(str(exc), vault_action="create")


@web_bp.post("/vaults/rename")
def rename_vault():
    current_name = request.form.get("current_name", "")
    new_name = request.form.get("new_name", "")
    try:
        get_service().rename_vault(current_name, new_name)
        return redirect_home(vault=new_name.strip())
    except (LockedError, ValidationError, NotFoundError, StorageError) as exc:
        return redirect_with_feedback(str(exc), vault=current_name, vault_action="rename")


@web_bp.post("/vaults/delete")
def delete_vault():
    name = request.form.get("name", "")
    try:
        get_service().delete_vault(name)
        remaining_vaults = get_service().list_vaults()
        next_vault = remaining_vaults[0]["name"] if remaining_vaults else None
        return redirect_home(vault=next_vault)
    except (LockedError, ValidationError, NotFoundError, StorageError) as exc:
        return redirect_with_feedback(str(exc), vault=name)


@web_bp.post("/secrets/create")
def create_secret():
    vault = request.form.get("vault", "")
    name = request.form.get("name", "")
    value = request.form.get("value", "")
    try:
        get_service().create_secret(vault, name, value, {})
        return redirect_home(vault=vault, target="secret")
    except (LockedError, ValidationError, NotFoundError, StorageError) as exc:
        return redirect_with_feedback(str(exc), vault=vault, create_secret=True)


@web_bp.post("/secrets/rename")
def rename_secret():
    vault = request.form.get("vault", "")
    current_name = request.form.get("current_name", "")
    new_name = request.form.get("new_name", "")
    try:
        get_service().rename_secret(vault, current_name, new_name)
        secret_name = new_name.strip()
        return redirect_home(vault=vault, secret=secret_name, expanded=merged_expanded_list(expanded_values_from_request(request.form), secret_name), target="secret")
    except (LockedError, ValidationError, NotFoundError, StorageError) as exc:
        return redirect_with_feedback(
            str(exc),
            vault=vault,
            secret=current_name,
            expanded=expanded_values_from_request(request.form),
            target="secret",
            editor_secret=current_name,
            editor_mode="rename",
        )


@web_bp.post("/secrets/update")
def update_secret():
    vault = request.form.get("vault", "")
    name = request.form.get("name", "")
    value = request.form.get("value", "")
    try:
        get_service().update_secret_value(vault, name, value)
        return redirect_home(vault=vault, secret=name, expanded=merged_expanded_list(expanded_values_from_request(request.form), name), target="secret")
    except (LockedError, ValidationError, NotFoundError, StorageError) as exc:
        return redirect_with_feedback(
            str(exc),
            vault=vault,
            secret=name,
            expanded=expanded_values_from_request(request.form),
            target="secret",
            editor_secret=name,
            editor_mode="value",
        )


@web_bp.post("/secrets/delete")
def delete_secret():
    vault = request.form.get("vault", "")
    name = request.form.get("name", "")
    try:
        get_service().delete_secret(vault, name)
        remaining_expanded = [expanded_name for expanded_name in expanded_values_from_request(request.form) if expanded_name != name]
        return redirect_home(vault=vault, expanded=remaining_expanded)
    except (LockedError, ValidationError, NotFoundError, StorageError) as exc:
        return redirect_with_feedback(str(exc), vault=vault, secret=name, expanded=expanded_values_from_request(request.form))


@web_bp.post("/metadata/set")
def set_metadata():
    vault = request.form.get("vault", "")
    secret_name = request.form.get("secret_name", "")
    key = request.form.get("key", "")
    value = request.form.get("value", "")
    confirm_overwrite = request.form.get("confirm_overwrite") == "1"
    try:
        normalized_key = key.strip()
        existing_value = get_service().get_metadata_value(vault, secret_name, normalized_key)
        if existing_value is not None and not confirm_overwrite:
            return redirect_home(
                vault=vault,
                secret=secret_name,
                expanded=merged_expanded_list(expanded_values_from_request(request.form), secret_name),
                target="metadata",
                editor_secret=secret_name,
                editor_mode="metadata",
                pending_metadata_key=normalized_key,
                pending_metadata_value=value,
                pending_metadata_existing_value=str(existing_value),
            )
        get_service().add_or_update_metadata(vault, secret_name, normalized_key, value)
        return redirect_home(vault=vault, secret=secret_name, expanded=merged_expanded_list(expanded_values_from_request(request.form), secret_name), field=key.strip(), target="metadata-field")
    except (LockedError, ValidationError, NotFoundError, StorageError) as exc:
        return redirect_with_feedback(
            str(exc),
            vault=vault,
            secret=secret_name,
            expanded=merged_expanded_list(expanded_values_from_request(request.form), secret_name),
            target="metadata",
            editor_secret=secret_name,
            editor_mode="metadata",
            pending_metadata_key=key.strip(),
            pending_metadata_value=value,
        )


@web_bp.post("/metadata/delete")
def delete_metadata():
    vault = request.form.get("vault", "")
    secret_name = request.form.get("secret_name", "")
    key = request.form.get("key", "")
    try:
        get_service().delete_metadata(vault, secret_name, key)
        return redirect_home(vault=vault, secret=secret_name, expanded=merged_expanded_list(expanded_values_from_request(request.form), secret_name), target="metadata")
    except (LockedError, ValidationError, NotFoundError, StorageError) as exc:
        return redirect_with_feedback(
            str(exc),
            vault=vault,
            secret=secret_name,
            expanded=merged_expanded_list(expanded_values_from_request(request.form), secret_name),
            target="metadata",
        )


@web_bp.get("/ui/status")
def ui_status():
    service = get_service()
    return jsonify({"status": service.status(), "session_log": service.session_events()})
