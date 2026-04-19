import json
from datetime import timedelta
from pathlib import Path

from bs4 import BeautifulSoup

from app.web import parse_metadata_input
from app.session import now_utc


def _soup(response):
    return BeautifulSoup(response.get_data(as_text=True), "html.parser")


def _last_event_text(response):
    return _soup(response).select_one("#last-event").get_text(" ", strip=True)


def _has_class(element, class_name):
    return element is not None and class_name in (element.get("class") or [])


def _text(element):
    return element.get_text(" ", strip=True) if element is not None else ""


def _texts(elements):
    return [_text(element) for element in elements]


def _css_text():
    return Path("app/static/css/app.css").read_text(encoding="utf-8")


def _js_text():
    return Path("app/static/js/app.js").read_text(encoding="utf-8")


def test_ui_shows_database_initialization_controls_when_db_missing(client):
    response = client.get("/")
    soup = _soup(response)
    assert response.status_code == 200
    assert soup.select_one(".banner") is None
    assert soup.select_one("#status-panel") is not None
    assert not soup.select_one("#status-panel").has_attr("open")
    assert soup.select_one("#merged-status").get_text(strip=True) == "Locked · Setup required"
    assert _has_class(soup.select_one("#summary-unlock-button"), "hidden")
    assert soup.select_one("#summary-unlock-button").has_attr("disabled")
    assert _has_class(soup.select_one("#unlock-form"), "hidden")
    assert soup.select_one("#unlock-passphrase").has_attr("disabled")
    assert soup.select_one("#unlock-submit-button").has_attr("disabled")
    assert b"Initialize Database" in response.data
    assert soup.select_one("#database-action-reset") is None
    assert soup.select_one("#database-action-change-passphrase") is None
    assert b"Database file is missing. Initialize a new database to begin." in response.data


def test_ui_top_panel_expanded_view_shows_compact_controls(client):
    response = client.get("/?panel=expanded")
    soup = _soup(response)

    assert response.status_code == 200
    assert soup.select_one("#status-panel").has_attr("open")
    assert soup.select_one('input[name="timeout_minutes"]') is not None
    assert soup.select_one('input[name="lock_on_invalid_api_request"]') is not None
    assert soup.select_one('input[name="lock_on_invalid_api_request"]').has_attr("checked")
    assert soup.select_one("#database-action-initialize") is not None
    assert not soup.select_one("#database-action-initialize").has_attr("open")
    assert soup.select_one("#database-action-reset") is None


def test_ui_top_panel_expanded_styles_do_not_render_separator_rule():
    css = _css_text()

    assert ".ops-body {\n  border-top: 1px solid var(--line);" not in css
    assert ".ops-body {\n  padding: 0 14px 14px;" in css


def test_ui_database_lifecycle_disclosure_uses_uniform_toggle_labels():
    css = _css_text()

    assert 'content: "Show controls";' in css
    assert 'content: "Hide controls";' in css
    assert "Reveal destructive form" not in Path("app/templates/index.html").read_text(encoding="utf-8")
    assert "Reveal rotation form" not in Path("app/templates/index.html").read_text(encoding="utf-8")


def test_ui_database_lifecycle_disclosure_body_has_no_inner_separator_rule():
    css = _css_text()

    assert ".action-body {\n  padding: 0 12px 12px;\n}" in css
    assert ".action-body {\n  padding: 0 12px 12px;\n  border-top: 1px solid var(--line);\n}" not in css


def test_ui_references_split_static_assets(client):
    response = client.get("/")
    soup = _soup(response)

def test_ui_uses_local_secrets_manager_branding(client):
    response = client.get("/")
    soup = _soup(response)
    assert _text(soup.select_one("title")) == "Local Secrets Manager"
    assert _text(soup.select_one("h1")) == "Local Secrets Manager"


    stylesheet = soup.select_one('link[href="/static/css/app.css"]')
    script = soup.select_one('script[src="/static/js/app.js"]')

    assert response.status_code == 200
    assert stylesheet is not None
    assert script is not None
    assert "<style>" not in response.get_data(as_text=True)


def test_ui_top_panel_collapsed_state_shows_lock_control_for_unlocked_service(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")

    response = client.get("/")
    soup = _soup(response)

    assert soup.select_one("#merged-status").get_text(strip=True) == "Unlocked · Ready"
    assert _has_class(soup.select_one("#summary-unlock-button"), "hidden")
    assert not _has_class(soup.select_one("#summary-lock-form"), "hidden")


def test_ui_database_initialization_flow(client):
    response = client.post(
        "/database/initialize",
        data={"passphrase": "passphrase", "confirm_passphrase": "passphrase", "panel": "expanded"},
        follow_redirects=True,
    )
    soup = _soup(response)
    assert response.status_code == 200
    assert soup.select_one(".banner") is None
    assert _last_event_text(response).endswith("Database initialized. Unlock it to continue.")
    assert soup.select_one("#status-panel").has_attr("open")
    assert b"Ready" in response.data
    assert b"Database created successfully. Unlock it with the new passphrase." in response.data
    assert b"Database is initialized. Unlock it with its passphrase" not in response.data


def test_ui_unlock_flow_after_initialization(client):
    client.post("/database/initialize", data={"passphrase": "passphrase", "confirm_passphrase": "passphrase"})
    response = client.post("/unlock", data={"passphrase": "passphrase", "panel": "expanded"}, follow_redirects=True)
    soup = _soup(response)
    assert response.status_code == 200
    assert soup.select_one("#merged-status").get_text(strip=True) == "Unlocked · Ready"
    assert _last_event_text(response).endswith("Service unlocked.")
    assert b"Database is unlocked and ready." in response.data


def test_ui_unlock_failure_message(client):
    client.post("/database/initialize", data={"passphrase": "passphrase", "confirm_passphrase": "passphrase"})
    response = client.post("/unlock", data={"passphrase": "wrong", "panel": "expanded"}, follow_redirects=True)
    assert response.status_code == 200
    assert _last_event_text(response).endswith("Unlock failed: Incorrect passphrase for the existing database.")


def test_ui_status_endpoint_reports_missing_database_after_runtime_deletion(client, app, temp_paths):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")

    (temp_paths / "secrets.db").unlink()

    response = client.get("/ui/status")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["status"]["database_state"] == "missing"
    assert payload["status"]["database_ready"] is False
    assert payload["status"]["database_unlockable"] is False
    assert payload["status"]["locked"] is True
    assert payload["status"]["unlocked"] is False
    assert payload["status"]["database_message"] == "Database file is missing. Initialize a new database to begin."


def test_ui_hides_unlock_and_keeps_lifecycle_controls_coherent_after_database_disappears(client, app, temp_paths):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")

    (temp_paths / "secrets.db").unlink()

    response = client.get("/?panel=expanded")
    soup = _soup(response)

    assert response.status_code == 200
    assert soup.select_one("#merged-status").get_text(strip=True) == "Locked · Setup required"
    assert _has_class(soup.select_one("#summary-unlock-button"), "hidden")
    assert _has_class(soup.select_one("#unlock-form"), "hidden")
    assert soup.select_one("#unlock-passphrase").has_attr("disabled")
    assert soup.select_one("#unlock-submit-button").has_attr("disabled")
    assert soup.select_one("#database-action-initialize") is not None
    assert soup.select_one("#database-action-reset") is None
    assert soup.select_one("#database-action-change-passphrase") is None
    assert b"Database file is missing. Initialize a new database to begin." in response.data


def test_ui_unlock_post_while_database_missing_keeps_missing_state_feedback(client, app, temp_paths):
    service = app.config["service"]
    service.initialize_database("passphrase")
    (temp_paths / "secrets.db").unlink()

    response = client.post("/unlock", data={"passphrase": "passphrase", "panel": "expanded"}, follow_redirects=True)
    soup = _soup(response)

    assert response.status_code == 200
    assert _last_event_text(response).endswith("Unlock failed: Database file is missing. Initialize a new database to begin.")
    assert soup.select_one("#merged-status").get_text(strip=True) == "Locked · Setup required"
    assert _has_class(soup.select_one("#summary-unlock-button"), "hidden")
    assert _has_class(soup.select_one("#unlock-form"), "hidden")


def test_ui_shows_selected_vault_and_retrieval_helper(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "test", "owner": "me"})

    response = client.get("/?vault=dev&secret=api-key")
    assert response.status_code == 200
    assert b"/api/v1/vaults/dev/secrets/api-key" in response.data
    assert b"print(response.json()" in response.data
    assert b"curl -fsS" in response.data
    assert b"| python -c" not in response.data


def test_ui_invalid_selected_vault_falls_back_to_first_vault(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("beta")
    service.create_vault("alpha")

    response = client.get("/?vault=missing")
    assert response.status_code == 200
    assert b"Secrets In alpha" in response.data


def test_ui_single_vault_is_auto_selected(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("alpha")

    response = client.get("/")
    soup = _soup(response)
    selected_row = soup.select_one('.vault-row[data-vault-name="alpha"]')

    assert response.status_code == 200
    assert selected_row is not None
    assert _has_class(selected_row, "selected")
    assert b"Secrets In alpha" in response.data


def test_ui_vault_management_uses_selectable_list_without_dropdown_flow(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("alpha")
    service.create_vault("beta")

    response = client.get("/?vault=beta")
    soup = _soup(response)
    selected_row = soup.select_one('.vault-row[data-vault-name="beta"]')

    assert soup.select_one('select[name="vault"]') is None
    assert "Select Active Vault" not in response.get_data(as_text=True)
    assert "Active Vault" not in response.get_data(as_text=True)
    assert selected_row is not None
    assert _has_class(selected_row, "selected")


def test_ui_vault_actions_are_disabled_when_no_vault_exists(client):
    client.post("/database/initialize", data={"passphrase": "passphrase", "confirm_passphrase": "passphrase"})
    client.post("/unlock", data={"passphrase": "passphrase"})

    response = client.get("/")
    soup = _soup(response)
    toolbar = soup.select_one(".vault-actions-toolbar")
    labels = [element.get_text(" ", strip=True) for element in toolbar.select("a, button")]

    assert response.status_code == 200
    assert labels == ["Create", "Rename", "Delete"]
    assert ".vault-actions-toolbar {\n  display: flex;\n  gap: 8px;\n  align-items: center;\n  flex-wrap: nowrap;\n}" in _css_text()
    assert soup.select_one(".vault-actions-toolbar a").get_text(" ", strip=True) == "Create"
    assert soup.select_one('.vault-actions-toolbar button[disabled]').get_text(" ", strip=True) == "Rename"
    assert soup.select_one('form[action="/vaults/delete"] button').has_attr("disabled")


def test_ui_selected_vault_renders_without_active_badge(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("alpha")

    response = client.get("/")
    soup = _soup(response)
    selected_row = soup.select_one('.vault-row[data-vault-name="alpha"]')

    assert selected_row is not None
    assert selected_row.select_one(".selection-badge") is None
    assert "Active Vault" not in _text(selected_row)


def test_ui_vault_create_and_rename_inputs_stay_hidden_until_requested(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")

    response = client.get("/?vault=dev")
    soup = _soup(response)

    assert soup.select_one("#create-vault-form") is None
    assert soup.select_one("#rename-vault-form") is None


def test_ui_with_no_vaults_shows_empty_state(client):
    client.post("/database/initialize", data={"passphrase": "passphrase", "confirm_passphrase": "passphrase"})
    client.post("/unlock", data={"passphrase": "passphrase"})
    response = client.get("/")
    soup = _soup(response)
    assert response.status_code == 200
    assert b"Create a vault to start storing secrets." in response.data
    assert b"Select a vault, secret, or metadata field to generate a helper." in response.data
    assert soup.select_one("#create-secret-toggle").has_attr("disabled")


def test_ui_session_log_renders_below_page_grid(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")

    response = client.get("/")
    soup = _soup(response)

    assert soup.select_one(".page-grid + #retrieval-helper-panel") is not None
    assert soup.select_one("#retrieval-helper-panel + #session-log-panel") is not None
    assert soup.select_one(".utility-column #session-log-panel") is None


def test_ui_runtime_log_uses_runtime_label_and_collapsed_summary_text(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")

    for index in range(6):
        service.session.log(f"event-{index}", level="warning" if index % 2 else "info")

    response = client.get("/")
    soup = _soup(response)
    preview_items = [item.get_text(" ", strip=True) for item in soup.select("#session-log-preview li")]
    full_items = [item.get_text(" ", strip=True) for item in soup.select("#session-log-full li")]
    summary = soup.select_one("#session-log-panel > summary")

    assert "Runtime Log" in summary.get_text(" ", strip=True)
    assert "Session Log" not in summary.get_text(" ", strip=True)
    assert summary.select_one(".session-log-state-collapsed").get_text(strip=True) == "Latest 5 events"
    assert summary.select_one(".session-log-state-expanded").get_text(strip=True) == "Full runtime log"
    assert len(preview_items) == 5
    assert preview_items == full_items[:5]
    assert all("event-" in item or "Database initialized." in item for item in preview_items)
    assert summary is not None
    assert summary.select_one("#session-log-preview") is not None


def test_ui_runtime_log_collapsed_preview_height_is_sized_for_five_entries():
    css = _css_text()

    assert ".session-log-preview {\n  margin-top: 12px;\n  max-height: 204px;\n  overflow: hidden;\n}" in css


def test_ui_runtime_log_collapsed_preview_renders_five_latest_entries_without_extra_rows(client, app):
    service = app.config["service"]

    for index in range(5):
        service.session.log(f"event-{index}")

    response = client.get("/")
    soup = _soup(response)
    preview_items = soup.select("#session-log-preview li")

    assert len(preview_items) == 5
    assert ".log-preview li:nth-child(n + 6) {\n  display: none;\n}" in _css_text()


def test_ui_session_log_expanded_container_renders_full_scrollable_log(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")

    for index in range(12):
        service.session.log(f"event-{index}")

    response = client.get("/")
    soup = _soup(response)
    full_items = soup.select("#session-log-full li")
    scroll_container = soup.select_one("#session-log-scroll")
    css = _css_text()

    assert soup.select_one("#session-log-panel") is not None
    assert scroll_container is not None
    assert len(full_items) == len(service.session_events())
    assert ".session-log-scroll {\n  max-height: 320px;\n  overflow: auto;" in css
    assert ".session-log-panel[open] .session-log-state-collapsed," in css
    assert ".session-log-panel:not([open]) .session-log-state-expanded {" in css


def test_ui_session_log_expanded_filters_by_level(client, app):
    service = app.config["service"]
    service.session.log("info-entry", level="info")
    service.session.log("security-entry", level="security")
    service.session.log("warning-entry", level="warning")

    response = client.get("/?panel=expanded&log_level=security")
    soup = _soup(response)
    full_items = [item.get_text(" ", strip=True) for item in soup.select("#session-log-full li")]

    assert any("security-entry" in item for item in full_items)
    assert all("warning-entry" not in item for item in full_items)
    assert soup.select_one('input.session-log-level-filter[value="security"]').has_attr("checked")


def test_ui_session_log_expanded_filters_by_text(client, app):
    service = app.config["service"]
    service.session.log("alpha-entry", level="info")
    service.session.log("bravo-entry", level="error")

    response = client.get("/?panel=expanded&log_q=bravo")
    soup = _soup(response)
    full_items = [item.get_text(" ", strip=True) for item in soup.select("#session-log-full li")]

    assert any("bravo-entry" in item for item in full_items)
    assert all("alpha-entry" not in item for item in full_items)
    assert soup.select_one("#session-log-search").get("value") == "bravo"


def test_ui_session_log_renders_level_classes_for_color_coding(client, app):
    service = app.config["service"]
    service.session.log("security-entry", level="security")

    response = client.get("/?panel=expanded")
    soup = _soup(response)
    css = _css_text()
    security_item = soup.select_one("#session-log-full .log-level-security")
    security_badge = soup.select_one("#session-log-full .log-level-badge-security")

    assert security_item is not None
    assert security_badge is not None
    assert ".log-level-security {" in css
    assert ".log-level-badge-success {" in css


def test_ui_runtime_log_entries_render_as_single_lines(client, app):
    service = app.config["service"]
    service.session.log(
        "Auto-lock triggered after inactivity.",
        level="warning",
        remote_addr="192.168.1.218",
        method="GET",
        path="/api/v1/status",
        status=200,
    )

    response = client.get("/?panel=expanded")
    soup = _soup(response)
    entry = soup.select_one("#session-log-full li")

    assert entry is not None
    assert entry.select_one(".log-entry-line") is not None
    assert entry.select_one(".log-level-badge.log-level-badge-warning") is not None
    assert entry.select_one(".log-entry-text") is not None
    assert entry.select_one(".log-entry-meta") is None
    assert entry.select_one(".log-entry-message") is None
    assert "[warning]" not in entry.get_text(" ", strip=True)
    assert entry.get_text(" ", strip=True) == " ".join(
        [
            "warning",
            service.session_events()[0]["timestamp"],
            "192.168.1.218",
            "GET",
            "/api/v1/status",
            "200",
            "Auto-lock triggered after inactivity.",
        ]
    )


def test_ui_unlocked_page_includes_state_regions_for_live_locked_refresh(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "test"})

    response = client.get("/?vault=dev&secret=api-key")
    soup = _soup(response)

    assert response.status_code == 200
    assert soup.select_one('[data-requires-unlocked] .vault-actions-toolbar a[href*="vault_action=create"]') is not None
    assert soup.select_one('[data-requires-unreachable]') is not None
    assert not _has_class(soup.select_one("#vault-count"), "hidden")
    assert _has_class(soup.select_one('[data-requires-locked][action="/unlock"]'), "hidden")
    assert _has_class(soup.select_one('[data-requires-locked].box-centered'), "hidden")


def test_ui_refresh_script_handles_locked_and_unreachable_states_centrally():
    script = Path("app/static/js/app.js").read_text(encoding="utf-8")

    assert "function updateStateRegions(mode)" in script
    assert 'querySelectorAll("[data-requires-unlocked], [data-requires-locked], [data-requires-unreachable]")' in script
    assert "function applyUnavailableState()" in script
    assert 'setServiceAvailability(false);' in script
    assert 'mergedStatus.textContent = buildMergedStatus({ unlocked: false, database_state: "ready" }, "unreachable");' in script


def test_ui_unreachable_state_styles_and_badge_styles_are_present():
    css = _css_text()

    assert '.status-pill[data-state="unreachable"] {' in css
    assert ".log-level-badge {" in css


def test_ui_manual_lock_creates_runtime_log_entry_and_updates_last_event(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    client.post(
        "/unlock",
        data={"passphrase": "passphrase", "panel": "expanded"},
        environ_overrides={"REMOTE_ADDR": "192.168.1.218"},
    )

    response = client.post(
        "/lock",
        data={"panel": "expanded"},
        environ_overrides={"REMOTE_ADDR": "192.168.1.218"},
        follow_redirects=True,
    )
    latest = service.session_events()[0]

    assert response.status_code == 200
    assert latest["message"] == "Service locked."
    assert latest["remote_addr"] == "192.168.1.218"
    assert latest["method"] == "POST"
    assert latest["path"] == "/lock"
    assert service.status()["last_event"] == latest["rendered"]
    assert _last_event_text(response) == latest["rendered"]


def test_ui_reset_database_replaces_existing_db(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "test"})
    service.lock()

    response = client.post(
        "/database/reset",
        data={"confirmation": "RESET", "new_passphrase": "fresh-passphrase", "confirm_passphrase": "fresh-passphrase", "panel": "expanded"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Database reset. Unlock it with the new passphrase to continue." in response.data
    assert b"Database reset successfully. Unlock it with the new passphrase." in response.data
    assert b"Database is initialized. Unlock it with its passphrase" not in response.data
    assert b"Reset And Reinitialize Database" in response.data

    ok, message = service.unlock("fresh-passphrase")
    assert ok is True, message
    assert service.list_vaults() == []


def test_ui_reset_database_requires_confirmation(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")

    response = client.post(
        "/database/reset",
        data={"confirmation": "WRONG", "new_passphrase": "fresh-passphrase", "confirm_passphrase": "fresh-passphrase", "panel": "expanded"},
        follow_redirects=True,
    )
    assert b"Type RESET to confirm database replacement." in response.data


def test_ui_database_action_forms_stay_collapsed_until_opened(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")

    response = client.get("/?panel=expanded")
    soup = _soup(response)

    reset_action = soup.select_one("#database-action-reset")
    change_action = soup.select_one("#database-action-change-passphrase")

    assert reset_action is not None
    assert not reset_action.has_attr("open")
    assert change_action is not None
    assert not change_action.has_attr("open")


def test_ui_vault_create_rename_delete_flows(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")

    response = client.post("/vaults/create", data={"name": "dev"}, follow_redirects=True)
    assert b"Vault created." in response.data

    response = client.post(
        "/vaults/rename",
        data={"current_name": "dev", "new_name": "dev-renamed"},
        follow_redirects=True,
    )
    assert b"Vault renamed." in response.data

    response = client.post("/vaults/delete", data={"name": "dev-renamed"}, follow_redirects=True)
    assert b"Vault deleted." in response.data


def test_ui_vault_delete_missing_shows_error(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")

    response = client.post("/vaults/delete", data={"name": "missing"}, follow_redirects=True)
    assert b"Vault not found." in response.data


def test_ui_secret_and_metadata_flows(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")

    response = client.post(
        "/secrets/create",
        data={"vault": "dev", "name": "api-key", "value": "secret-value"},
        follow_redirects=True,
    )
    assert b"Secret created." in response.data

    response = client.post(
        "/metadata/set",
        data={"vault": "dev", "secret_name": "api-key", "key": "owner", "value": "miguel"},
        follow_redirects=True,
    )
    assert b"Metadata saved." in response.data

    response = client.post(
        "/secrets/update",
        data={"vault": "dev", "name": "api-key", "value": "rotated-value"},
        follow_redirects=True,
    )
    assert b"Secret updated." in response.data

    response = client.post(
        "/secrets/rename",
        data={"vault": "dev", "current_name": "api-key", "new_name": "api-key-v2"},
        follow_redirects=True,
    )
    assert b"Secret renamed." in response.data

    response = client.post(
        "/metadata/delete",
        data={"vault": "dev", "secret_name": "api-key-v2", "key": "owner"},
        follow_redirects=True,
    )
    assert b"Metadata deleted." in response.data

    response = client.post(
        "/secrets/delete",
        data={"vault": "dev", "name": "api-key-v2"},
        follow_redirects=True,
    )
    assert b"Secret deleted." in response.data


def test_ui_adding_new_metadata_key_succeeds_without_confirmation(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"owner": "me"})

    response = client.post(
        "/metadata/set",
        data={"vault": "dev", "secret_name": "api-key", "key": "team", "value": "platform", "expanded_secret": "api-key"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Metadata saved." in response.data
    assert b"Overwrite existing value?" not in response.data
    assert service.read_secret("dev", "api-key")["metadata"]["team"] == "platform"


def test_ui_duplicate_metadata_key_requires_inline_overwrite_confirmation(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"owner": "me"})

    response = client.post(
        "/metadata/set",
        data={"vault": "dev", "secret_name": "api-key", "key": "owner", "value": "you", "expanded_secret": "api-key"},
        follow_redirects=True,
    )
    soup = _soup(response)
    warning = soup.select_one("#metadata-overwrite-warning")

    assert response.status_code == 200
    assert warning is not None
    assert 'Metadata key "owner" already exists.' in warning.get_text(" ", strip=True)
    assert "Overwrite existing value?" in warning.get_text(" ", strip=True)
    assert "Old: me" in warning.get_text(" ", strip=True)
    assert "New: you" in warning.get_text(" ", strip=True)
    assert service.read_secret("dev", "api-key")["metadata"]["owner"] == "me"


def test_ui_confirming_duplicate_metadata_overwrite_replaces_existing_value(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"owner": "me"})

    response = client.post(
        "/metadata/set",
        data={
            "vault": "dev",
            "secret_name": "api-key",
            "key": "owner",
            "value": "you",
            "expanded_secret": "api-key",
            "confirm_overwrite": "1",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Metadata saved." in response.data
    assert service.read_secret("dev", "api-key")["metadata"]["owner"] == "you"


def test_ui_canceling_duplicate_metadata_overwrite_preserves_existing_value(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"owner": "me"})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key&target=metadata&editor_secret=api-key&editor_mode=metadata&pending_metadata_key=owner&pending_metadata_value=you&pending_metadata_existing_value=me")
    soup = _soup(response)
    cancel_link = soup.select_one('form[data-editor-mode="metadata"] a[href]')

    assert cancel_link is not None

    canceled = client.get(cancel_link.get("href"), follow_redirects=True)
    canceled_soup = _soup(canceled)

    assert canceled.status_code == 200
    assert canceled_soup.select_one("#metadata-overwrite-warning") is None
    assert service.read_secret("dev", "api-key")["metadata"]["owner"] == "me"


def test_ui_secret_rename_missing_shows_error(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")

    response = client.post(
        "/secrets/rename",
        data={"vault": "dev", "current_name": "missing", "new_name": "new-name"},
        follow_redirects=True,
    )
    assert b"Secret not found." in response.data


def test_ui_secret_update_missing_shows_error(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")

    response = client.post(
        "/secrets/update",
        data={"vault": "dev", "name": "missing", "value": "value"},
        follow_redirects=True,
    )
    assert b"Secret not found." in response.data


def test_ui_secret_delete_missing_shows_error(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")

    response = client.post(
        "/secrets/delete",
        data={"vault": "dev", "name": "missing"},
        follow_redirects=True,
    )
    assert b"Secret not found." in response.data


def test_ui_create_secret_inputs_are_hidden_by_default(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")

    response = client.get("/?vault=dev")
    soup = _soup(response)
    create_toggle = soup.select_one("#create-secret-toggle")

    assert create_toggle is not None
    assert _text(create_toggle) == "Create Secret"
    assert soup.select_one("#create-secret-form") is None
    assert soup.select_one('form[action="/secrets/create"]') is None


def test_ui_clicking_create_secret_reveals_compact_inline_form(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")

    response = client.get("/?vault=dev&create_secret=1")
    soup = _soup(response)
    create_form = soup.select_one("#create-secret-form")

    assert create_form is not None
    assert create_form.select_one('[name="metadata"]') is None
    assert create_form.select_one('textarea[name="value"]') is None
    assert create_form.select_one('input[name="name"]') is not None
    assert create_form.select_one('input[name="value"]') is not None
    assert create_form.select_one('button[type="submit"]').get_text(" ", strip=True) == "Create"
    assert create_form.select_one('a').get_text(" ", strip=True) == "Cancel"


def test_ui_successful_secret_creation_collapses_inline_create_form(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")

    response = client.post(
        "/secrets/create",
        data={"vault": "dev", "name": "api-key", "value": "secret-value"},
        follow_redirects=True,
    )
    soup = _soup(response)

    assert response.status_code == 200
    assert soup.select_one("#create-secret-form") is None
    assert _text(soup.select_one("#create-secret-toggle")) == "Create Secret"


def test_parse_metadata_input_rejects_non_object_json():
    try:
        parse_metadata_input('["a", "b"]')
    except Exception as exc:
        assert str(exc) == "Metadata must be a JSON object."
    else:
        raise AssertionError("Expected validation error for non-object metadata JSON")


def test_ui_locked_management_actions_show_error(client):
    client.post("/database/initialize", data={"passphrase": "passphrase", "confirm_passphrase": "passphrase"})
    response = client.post("/vaults/create", data={"name": "dev"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Service is locked." in response.data


def test_ui_change_passphrase_success(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {})

    response = client.post(
        "/database/change-passphrase",
        data={"current_passphrase": "passphrase", "new_passphrase": "rotated", "confirm_passphrase": "rotated", "panel": "expanded"},
        follow_redirects=True,
    )
    assert b"Passphrase changed." in response.data

    service.lock()
    ok, message = service.unlock("rotated")
    assert ok is True, message
    assert service.read_secret("dev", "api-key")["value"] == "secret-value"


def test_ui_change_passphrase_wrong_current_shows_error(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")

    response = client.post(
        "/database/change-passphrase",
        data={"current_passphrase": "wrong", "new_passphrase": "rotated", "confirm_passphrase": "rotated", "panel": "expanded"},
        follow_redirects=True,
    )
    assert b"Current passphrase is incorrect." in response.data


def test_ui_change_passphrase_while_locked_shows_error(client):
    client.post("/database/initialize", data={"passphrase": "passphrase", "confirm_passphrase": "passphrase"})

    response = client.post(
        "/database/change-passphrase",
        data={"current_passphrase": "passphrase", "new_passphrase": "rotated", "confirm_passphrase": "rotated", "panel": "expanded"},
        follow_redirects=True,
    )
    assert b"Service is locked." in response.data


def test_ui_change_passphrase_blank_new_value_shows_error(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")

    response = client.post(
        "/database/change-passphrase",
        data={"current_passphrase": "passphrase", "new_passphrase": "  ", "confirm_passphrase": "  ", "panel": "expanded"},
        follow_redirects=True,
    )
    assert b"New passphrase is required." in response.data


def test_ui_helper_updates_for_metadata_field(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key&field=env&target=metadata-field")
    assert response.status_code == 200
    assert b"/api/v1/vaults/dev/secrets/api-key/metadata" in response.data
    assert b"response.json()" in response.data


def test_ui_secrets_render_collapsed_by_default_and_hide_metadata_controls(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})

    response = client.get("/?vault=dev")
    soup = _soup(response)
    secret_row = soup.select_one('.secret-row[data-secret-name="api-key"]')

    assert secret_row is not None
    assert not _has_class(secret_row, "is-expanded")
    assert secret_row.select_one('form[action="/secrets/rename"]') is None
    assert secret_row.select_one('form[action="/secrets/update"]') is None
    assert secret_row.select_one('form[action="/metadata/set"]') is None
    assert secret_row.select_one(".secret-inline-editor") is None
    assert _text(secret_row.select_one(".secret-value")) == "••••••••"
    assert secret_row.select_one(".secret-action-row") is None
    assert secret_row.select_one(".secret-metadata-panel") is None
    assert "Selected Secret" not in _text(secret_row)
    assert "metadata field" not in _text(secret_row)
    assert "Updated " not in _text(secret_row)


def test_ui_expanding_secret_reveals_edit_and_metadata_controls(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key")
    soup = _soup(response)
    secret_row = soup.select_one('.secret-row[data-secret-name="api-key"]')

    assert secret_row is not None
    assert _has_class(secret_row, "is-expanded")
    assert _texts(secret_row.select(".secret-action-row a, .secret-action-row button")) == [
        "Edit Name",
        "Update Secret Value",
        "Add Metadata",
        "Delete Secret",
    ]
    assert secret_row.select_one('form[action="/secrets/rename"]') is None
    assert secret_row.select_one('form[action="/secrets/update"]') is None
    assert secret_row.select_one(".secret-metadata-panel") is not None
    assert secret_row.select_one('form[action="/metadata/delete"]') is not None
    assert secret_row.select_one('form[action="/metadata/set"]') is None
    assert secret_row.select_one(".secret-action-row") is not None


def test_ui_retrieval_helper_tracks_selected_secret_metadata_collection_and_field(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})

    secret_response = client.get("/?vault=dev&secret=api-key")
    expanded_response = client.get("/?vault=dev&secret=api-key&expanded=api-key&target=metadata")
    field_response = client.get("/?vault=dev&secret=api-key&expanded=api-key&field=env&target=metadata-field")
    secret_soup = _soup(secret_response)
    expanded_soup = _soup(expanded_response)
    field_soup = _soup(field_response)

    assert b'/api/v1/vaults/dev/secrets/api-key' in secret_response.data
    assert 'print(response.json()["value"])' in _text(secret_soup.select_one("#helper-python"))
    assert _text(expanded_soup.select_one("#helper-collapsed-api-path")) == "/api/v1/vaults/dev/secrets/api-key/metadata"
    assert b'/api/v1/vaults/dev/secrets/api-key/metadata' in expanded_response.data
    assert "metadata = response.json()" in _text(expanded_soup.select_one("#helper-python"))
    assert "print(metadata)" in _text(expanded_soup.select_one("#helper-python"))
    assert 'payload["metadata"]' not in _text(expanded_soup.select_one("#helper-python"))
    assert _text(field_soup.select_one("#helper-collapsed-api-path")) == "/api/v1/vaults/dev/secrets/api-key/metadata/env"
    assert 'requests.get("http://127.0.0.1:5000/api/v1/vaults/dev/secrets/api-key/metadata/env")' in _text(field_soup.select_one("#helper-python"))
    assert "field_value = response.json()" in _text(field_soup.select_one("#helper-python"))
    assert "print(field_value)" in _text(field_soup.select_one("#helper-python"))


def test_ui_metadata_helper_matches_flat_collection_response_shape(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev", "owner": "miguel"})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key&target=metadata")
    helper_python = _text(_soup(response).select_one("#helper-python"))

    assert response.status_code == 200
    assert 'requests.get("http://127.0.0.1:5000/api/v1/vaults/dev/secrets/api-key/metadata")' in helper_python
    assert "metadata = response.json()" in helper_python
    assert "print(metadata)" in helper_python
    assert 'payload["metadata"]' not in helper_python


def test_ui_missing_metadata_selection_falls_back_gracefully(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})

    response = client.get("/?vault=dev&secret=api-key&field=missing")
    soup = _soup(response)
    assert response.status_code == 200
    assert _text(soup.select_one("#helper-collapsed-api-path")) == "/api/v1/vaults/dev/secrets/api-key"
    assert 'print(response.json()["value"])' in _text(soup.select_one("#helper-python"))


def test_ui_locked_home_hides_management_sections(client):
    client.post("/database/initialize", data={"passphrase": "passphrase", "confirm_passphrase": "passphrase"})
    response = client.get("/")
    assert b"Unlock the service to manage vaults." in response.data
    assert b"Only locked-state and database lifecycle controls are available right now." in response.data


def test_ui_reveal_controls_are_disabled_while_locked(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {})
    service.lock()

    response = client.get("/?vault=dev&secret=api-key")
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    assert b"Only locked-state and database lifecycle controls are available right now." in response.data
    assert soup.select(".reveal-button") == []


def test_ui_reveal_script_keeps_show_fetch_and_auto_hide_behavior():
    script = _js_text()

    assert 'for (const button of document.querySelectorAll(".reveal-button")) {' in script
    assert "button.addEventListener(\"click\", async () => {" in script
    assert "target.textContent = payload.value;" in script
    assert 'button.textContent = "Hide";' in script
    assert "const timerId = window.setTimeout(() => maskSecret(button), 9000);" in script


def test_ui_visible_secret_value_region_is_marked_as_non_toggle_container(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key")
    soup = _soup(response)
    secret_value_region = soup.select_one('.secret-row[data-secret-name="api-key"] .secret-value-region')
    secret_value_display = soup.select_one('.secret-row[data-secret-name="api-key"] .secret-value-region .secret-value-display')
    secret_value = soup.select_one('.secret-row[data-secret-name="api-key"] .secret-value-region .secret-value')

    assert secret_value_region is not None
    assert secret_value_display is not None
    assert secret_value is not None
    assert secret_value_region.get("data-secret-value-zone") == "true"
    assert secret_value_region.get("data-prevent-row-toggle") == "true"
    assert secret_value_display.parent == secret_value_region
    assert secret_value.parent == secret_value_display


def test_ui_plain_secret_row_click_toggle_stays_wired():
    script = _js_text()

    assert 'wireSelectableContainers(".secret-row[data-select-url]");' in script


def test_ui_secret_selection_inside_value_area_suppresses_row_toggle():
    script = _js_text()

    assert '[data-secret-value-zone]' in script
    assert 'function shouldIgnoreSelectionClick(target)' in script
    assert 'function secretValueRegionForTarget(target)' in script
    assert 'return element.closest(".secret-value-region[data-secret-value-zone]");' in script


def test_ui_drag_selecting_anywhere_inside_secret_value_region_pauses_auto_hide_until_mouseup():
    script = _js_text()

    assert 'for (const valueRegion of document.querySelectorAll(".secret-value-region[data-secret-value-zone]")) {' in script
    assert "valueRegion.addEventListener(\"mousedown\", (event) => {" in script
    assert "function revealButtonForValueRegion(valueRegion)" in script
    assert "clearAutoHideTimer(button);" in script
    assert "document.addEventListener(\"mouseup\", () => {" in script
    assert "scheduleAutoHide(activeRevealSelectionButton);" in script


def test_ui_secret_value_region_styles_expand_selection_safe_area():
    css = _css_text()

    assert ".secret-value-region {" in css
    assert "flex: 1 1 18rem;" in css
    assert "min-width: 12rem;" in css
    assert ".secret-value-display {" in css
    assert "min-height: 2.25rem;" in css
    assert "width: 100%;" in css
    assert "padding: 6px 12px;" in css
    assert ".secret-value {\n  display: block;\n  width: 100%;\n  min-width: 0;\n  font-family: monospace;\n  user-select: text;\n  word-break: break-all;\n}" in css


def test_ui_right_click_inside_secret_value_region_does_not_start_toggle_or_selection_pause_logic():
    script = _js_text()

    assert "if (event.button !== 0) {" in script
    assert "valueRegion.addEventListener(\"contextmenu\", (event) => {" in script
    assert "if (!secretValueRegionForTarget(event.target)) {" in script
    assert "event.stopPropagation();" in script


def test_ui_plain_secret_row_click_toggle_remains_outside_value_container():
    script = _js_text()

    assert 'wireSelectableContainers(".secret-row[data-select-url]");' in script
    assert 'const url = element.dataset.selectUrl;' in script


def test_ui_corrupted_database_renders_error_message(client, temp_paths):
    (temp_paths / "secrets.db").write_bytes(b"bad-db")
    response = client.get("/")
    assert response.status_code == 200
    assert b"Database is unreadable or corrupted." in response.data
    assert b"Reset And Reinitialize Database" in response.data


def test_ui_database_message_stays_in_sync_after_initialize_then_unlock(client):
    client.post(
        "/database/initialize",
        data={"passphrase": "passphrase", "confirm_passphrase": "passphrase", "panel": "expanded"},
        follow_redirects=True,
    )

    response = client.post("/unlock", data={"passphrase": "passphrase", "panel": "expanded"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Database is unlocked and ready." in response.data
    assert b"Database created successfully. Unlock it with the new passphrase." not in response.data


def test_ui_status_endpoint_reflects_initialize_and_reset_database_messages(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")

    response = client.get("/ui/status")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"]["database_state"] == "ready"
    assert payload["status"]["database_message"] == "Database created successfully. Unlock it with the new passphrase."

    service.reset_database("fresh-passphrase", "RESET")
    response = client.get("/ui/status")
    payload = response.get_json()
    assert payload["status"]["database_message"] == "Database reset successfully. Unlock it with the new passphrase."


def test_ui_settings_flow_persists_to_config(client, temp_paths):
    response = client.post(
        "/settings",
        data={
            "selected_vault": "",
            "selected_secret": "",
            "timeout_enabled": "on",
            "timeout_minutes": "22",
            "panel": "expanded",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Session settings saved." in response.data

    config = json.loads((temp_paths / "config.json").read_text(encoding="utf-8"))
    assert config["timeout_enabled"] is True
    assert config["timeout_minutes"] == 22
    assert config["reset_on_read"] is False
    assert config["lock_on_invalid_api_request"] is False


def test_ui_settings_save_resets_countdown_to_new_timeout(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.session.timeout_enabled = True
    service.session.timeout_minutes = 30
    service.session.last_activity_at = now_utc() - timedelta(minutes=10)

    response = client.post(
        "/settings",
        data={
            "selected_vault": "",
            "selected_secret": "",
            "timeout_enabled": "on",
            "timeout_minutes": "1",
            "reset_on_read": "on",
            "lock_on_invalid_api_request": "on",
            "panel": "expanded",
        },
        follow_redirects=True,
    )
    soup = _soup(response)
    countdown_text = soup.select_one("#countdown").get_text(strip=True)

    assert response.status_code == 200
    assert b"Session settings saved." in response.data
    assert soup.select_one("#timeout-minutes-stat").get_text(strip=True) == "1 min"
    assert countdown_text in {"59s", "60s"}
    assert service.status()["locked"] is False


def test_ui_invalid_settings_shows_validation_error(client):
    response = client.post(
        "/settings",
        data={"timeout_enabled": "on", "timeout_minutes": "0", "reset_on_read": "on", "lock_on_invalid_api_request": "on", "panel": "expanded"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Timeout must be at least 1 minute." in response.data


def test_ui_secret_filter_scopes_to_selected_vault(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {})
    service.create_secret("dev", "db-password", "secret-value", {})

    response = client.get("/?vault=dev&q=api")
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    secret_links = [link.get_text(strip=True) for link in soup.select(".secret-row .secret-name-link")]
    assert response.status_code == 200
    assert secret_links == ["api-key"]


def test_ui_secret_filter_ui_no_longer_renders(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {})

    response = client.get("/?vault=dev")
    soup = _soup(response)

    assert "Filter secrets in this vault" not in response.get_data(as_text=True)
    assert soup.select_one(".secret-filter-form") is None


def test_ui_secret_controls_are_disabled_when_no_vault_exists(client):
    client.post("/database/initialize", data={"passphrase": "passphrase", "confirm_passphrase": "passphrase"})
    client.post("/unlock", data={"passphrase": "passphrase"})

    response = client.get("/")
    soup = _soup(response)
    create_toggle = soup.select_one("#create-secret-toggle")

    assert response.status_code == 200
    assert create_toggle is not None
    assert create_toggle.has_attr("disabled")
    assert soup.select_one("#create-secret-form") is None
    assert soup.select(".secret-row") == []


def test_ui_selected_vault_determines_which_secrets_are_shown(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("alpha")
    service.create_vault("beta")
    service.create_secret("alpha", "alpha-key", "secret-value", {})
    service.create_secret("beta", "beta-key", "secret-value", {})

    response = client.get("/?vault=beta")
    soup = _soup(response)
    rendered_names = [link.get_text(strip=True) for link in soup.select(".secret-row .secret-name-link")]

    assert response.status_code == 200
    assert rendered_names == ["beta-key"]
    assert "alpha-key" not in response.get_data(as_text=True)


def test_ui_deleting_selected_vault_clears_helper_context(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_vault("ops")
    service.create_secret("dev", "api-key", "secret-value", {})

    response = client.post("/vaults/delete", data={"name": "dev"}, follow_redirects=True)
    soup = _soup(response)
    assert response.status_code == 200
    assert b"Vault deleted." in response.data
    assert soup.select_one("#helper-collapsed-api-path") is None
    assert "Select a vault, secret, or metadata field to generate a helper." in _text(soup.select_one(".helper-preview"))
    assert b"/api/v1/vaults/dev/secrets/api-key" not in response.data


def test_ui_status_endpoint_returns_session_snapshot(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")

    response = client.get("/ui/status")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"]["unlocked"] is True
    assert isinstance(payload["session_log"], list)
    assert payload["status"]["lock_on_invalid_api_request"] is True


def test_ui_secret_row_click_state_is_encoded_in_select_url(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})

    collapsed_response = client.get("/?vault=dev")
    expanded_response = client.get("/?vault=dev&secret=api-key&expanded=api-key")
    collapsed_row = _soup(collapsed_response).select_one('.secret-row[data-secret-name="api-key"]')
    expanded_row = _soup(expanded_response).select_one('.secret-row[data-secret-name="api-key"]')

    assert collapsed_row.get("data-select-url") == "/?vault=dev&secret=api-key&expanded=api-key&target=secret"
    assert expanded_row.get("data-select-url") == "/?vault=dev&secret=api-key&target=secret"


def test_ui_multiple_vaults_allow_empty_selection_state(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("alpha")
    service.create_vault("beta")

    response = client.get("/")
    soup = _soup(response)

    assert response.status_code == 200
    assert soup.select_one(".vault-row.selected") is None
    assert b"Select a vault to view and manage its secrets." in response.data
    assert soup.select_one("#create-secret-toggle").has_attr("disabled")


def test_ui_workspace_uses_shared_scrollable_panel_hooks():
    html = Path("app/templates/index.html").read_text(encoding="utf-8")
    css = _css_text()

    assert 'class="page-grid workspace-grid"' in html
    assert 'class="panel workspace-panel workspace-panel-vaults"' in html
    assert 'class="panel workspace-panel workspace-panel-secrets"' in html
    assert 'id="vault-workspace-scroll"' in html
    assert 'id="secret-workspace-scroll"' in html
    assert "--workspace-height: 38rem;" in css
    assert ".workspace-panel {" in css
    assert "height: var(--workspace-height);" in css
    assert ".workspace-scroll {" in css
    assert "overflow: auto;" in css




def test_ui_supports_multiple_expanded_secrets_and_preserves_them_in_urls(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})
    service.create_secret("dev", "db-pass", "another-secret", {"owner": "miguel"})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key&expanded=db-pass")
    soup = _soup(response)

    api_row = soup.select_one('.secret-row[data-secret-name="api-key"]')
    db_row = soup.select_one('.secret-row[data-secret-name="db-pass"]')

    assert _has_class(api_row, "is-expanded")
    assert _has_class(db_row, "is-expanded")
    assert api_row.get("data-select-url") == "/?vault=dev&secret=api-key&expanded=db-pass&target=secret"
    assert db_row.get("data-select-url") == "/?vault=dev&secret=db-pass&expanded=api-key&target=secret"

def test_ui_secret_action_buttons_render_in_single_row(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key")
    soup = _soup(response)
    action_row = soup.select_one(".secret-action-row")
    labels = [element.get_text(" ", strip=True) for element in action_row.select("a, button")]

    assert action_row is not None
    assert "Edit Name" in labels
    assert "Update Secret Value" in labels
    assert "Add Metadata" in labels
    assert "Delete Secret" in labels


def test_ui_only_one_secret_sub_editor_renders_at_a_time(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})
    service.create_secret("dev", "db-pass", "another-secret", {})

    response = client.get("/?vault=dev&secret=db-pass&expanded=api-key&expanded=db-pass&editor_secret=db-pass&editor_mode=value")
    soup = _soup(response)

    assert len(soup.select(".secret-inline-editor")) == 1
    assert soup.select_one('.secret-row[data-secret-name="api-key"] .secret-inline-editor') is None
    assert soup.select_one('.secret-row[data-secret-name="db-pass"] .secret-inline-editor[data-editor-mode="value"]') is not None


def test_ui_edit_name_editor_renders_compact_inline_form(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key&editor_secret=api-key&editor_mode=rename")
    soup = _soup(response)
    editor = soup.select_one('.secret-inline-editor[data-editor-mode="rename"]')

    assert editor is not None
    assert editor.select_one('input[name="new_name"]') is not None
    assert editor.select_one('textarea') is None
    assert _texts(editor.select("button, a")) == ["Save", "Cancel"]


def test_ui_update_value_editor_renders_compact_inline_form(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key&editor_secret=api-key&editor_mode=value")
    soup = _soup(response)
    editor = soup.select_one('.secret-inline-editor[data-editor-mode="value"]')

    assert editor is not None
    assert editor.select_one('input[name="value"]') is not None
    assert editor.select_one('textarea') is None
    assert _texts(editor.select("button, a")) == ["Save", "Cancel"]


def test_ui_add_metadata_editor_renders_compact_inline_form(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key&editor_secret=api-key&editor_mode=metadata")
    soup = _soup(response)
    editor = soup.select_one('.secret-inline-editor[data-editor-mode="metadata"]')

    assert editor is not None
    assert editor.select_one('input[name="key"]') is not None
    assert editor.select_one('input[name="value"]') is not None
    assert editor.select_one('textarea') is None
    assert _texts(editor.select("button, a")) == ["Save", "Cancel"]


def test_ui_secret_inline_editor_expanded_state_has_no_extra_divider_or_rule(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key&editor_secret=api-key&editor_mode=rename")
    soup = _soup(response)
    css = _css_text()
    secret_row = soup.select_one('.secret-row[data-secret-name="api-key"]')

    assert secret_row.select_one("hr") is None
    assert ".secret-inline-editor {\n  border-top:" not in css
    assert secret_row.select_one(".inline-disclosure") is None


def test_ui_metadata_container_includes_system_and_user_metadata_cards(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key&target=metadata")
    soup = _soup(response)
    metadata_panel = soup.select_one(".metadata-container")
    cards = [_text(card) for card in soup.select(".metadata-card")]

    assert metadata_panel is not None
    assert _has_class(metadata_panel, "selected")
    assert any("Created" in card for card in cards)
    assert any("Updated" in card for card in cards)
    assert any("Last accessed" in card for card in cards)
    assert any("env" in card for card in cards)


def test_ui_metadata_selection_urls_are_distinct_and_keep_secret_expanded(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key")
    soup = _soup(response)
    secret_row = soup.select_one('.secret-row[data-secret-name="api-key"]')
    metadata_panel = soup.select_one(".metadata-container")
    metadata_card = soup.select_one('.metadata-card[data-select-url*="field=env"]')

    assert secret_row is not None
    assert metadata_panel is not None
    assert metadata_card is not None
    assert secret_row.get("data-select-url") == "/?vault=dev&secret=api-key&target=secret"
    assert metadata_panel.get("data-select-url") == "/?vault=dev&secret=api-key&expanded=api-key&target=metadata"
    assert metadata_card.get("data-select-url") == "/?vault=dev&secret=api-key&expanded=api-key&field=env&target=metadata-field"


def test_ui_metadata_field_selection_highlights_selected_card(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key&field=env&target=metadata-field")
    soup = _soup(response)
    selected_card = soup.select_one(".metadata-card.selected")

    assert selected_card is not None
    assert "env" in _text(selected_card)
    assert 'requests.get("http://127.0.0.1:5000/api/v1/vaults/dev/secrets/api-key/metadata/env")' in _text(soup.select_one("#helper-python"))


def test_ui_new_metadata_appears_as_card_inside_metadata_container(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {})

    response = client.post(
        "/metadata/set",
        data={"vault": "dev", "secret_name": "api-key", "key": "owner", "value": "miguel", "expanded_secret": "api-key"},
        follow_redirects=True,
    )
    soup = _soup(response)

    assert response.status_code == 200
    assert soup.select_one('.metadata-card[data-select-url*="field=owner"]') is not None
    assert "owner" in response.get_data(as_text=True)


def test_ui_retrieval_helper_hides_copy_buttons_and_keeps_single_path_preview(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key&target=secret")
    soup = _soup(response)

    assert soup.select(".copy-button") == []
    collapsed_preview = soup.select_one("#helper-collapsed-api-path")
    assert collapsed_preview is not None
    assert _text(collapsed_preview) == "/api/v1/vaults/dev/secrets/api-key"
    assert _texts(soup.select(".helper-preview code")) == ["/api/v1/vaults/dev/secrets/api-key"]

def test_ui_retrieval_helper_expanded_shows_all_outputs_and_full_width_structure(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})

    response = client.get("/?vault=dev&secret=api-key")
    soup = _soup(response)
    helper_panel = soup.select_one("#retrieval-helper-panel")

    assert soup.select_one("main #retrieval-helper-panel") is None
    assert soup.select_one(".page-grid + #retrieval-helper-panel") is not None
    assert helper_panel is not None
    assert helper_panel.select_one("#helper-api-path") is not None
    assert helper_panel.select_one("#helper-curl") is not None
    assert helper_panel.select_one("#helper-python") is not None
    assert _texts(helper_panel.select(".retrieval-helper-body .helper-output-label")) == [
        "HTTP path",
        "curl example",
        "Python example",
    ]


def test_ui_retrieval_helper_expanded_state_hides_collapsed_preview_to_avoid_path_duplication():
    css = _css_text()

    assert ".retrieval-helper-panel[open] .helper-preview {\n  display: none;\n}" in css


def test_ui_retrieval_helper_supports_system_metadata_field_selection(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key&field=created_at&target=metadata-field")
    soup = _soup(response)

    assert _text(soup.select_one("#helper-collapsed-api-path")) == "/api/v1/vaults/dev/secrets/api-key/metadata/created_at"
    assert 'requests.get("http://127.0.0.1:5000/api/v1/vaults/dev/secrets/api-key/metadata/created_at")' in _text(soup.select_one("#helper-python"))
    assert "field_value = response.json()" in _text(soup.select_one("#helper-python"))
    assert "print(field_value)" in _text(soup.select_one("#helper-python"))


def test_ui_retrieval_helper_collapsed_preview_renders_single_path_line_only(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key&field=env&target=metadata-field")
    soup = _soup(response)
    helper_preview = soup.select_one(".helper-preview")

    assert helper_preview is not None
    assert [child.name for child in helper_preview.find_all(recursive=False)] == ["code"]
    assert _text(helper_preview.select_one("#helper-collapsed-api-path")) == "/api/v1/vaults/dev/secrets/api-key/metadata/env"
    assert "HTTP path" not in _text(helper_preview)
    assert "curl example" not in _text(helper_preview)
    assert "Python example" not in _text(helper_preview)


def test_ui_retrieval_helper_empty_state_preview_stays_compact_and_usable(client):
    response = client.get("/")
    soup = _soup(response)
    helper_preview = soup.select_one(".helper-preview")

    assert helper_preview is not None
    assert [child.name for child in helper_preview.find_all(recursive=False)] == ["span"]
    assert _text(helper_preview) == "Select a vault, secret, or metadata field to generate a helper."


def test_ui_retrieval_helper_curl_output_contains_only_curl_request(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})

    response = client.get("/?vault=dev&secret=api-key&expanded=api-key&field=env&target=metadata-field")
    soup = _soup(response)
    curl_text = _text(soup.select_one("#helper-curl"))

    assert curl_text.startswith('curl -fsS "http://127.0.0.1:5000/api/v1/vaults/dev/secrets/api-key/metadata/env"')
    assert "|" not in curl_text
    assert "python" not in curl_text.lower()


def test_ui_retrieval_helper_is_collapsed_by_default_with_toggle_affordance(client, app):
    service = app.config["service"]
    service.initialize_database("passphrase")
    service.unlock("passphrase")
    service.create_vault("dev")
    service.create_secret("dev", "api-key", "secret-value", {"env": "dev"})

    response = client.get("/?vault=dev&secret=api-key")
    soup = _soup(response)
    helper_panel = soup.select_one("#retrieval-helper-panel")
    toggle = soup.select_one(".helper-toggle-affordance")

    assert helper_panel is not None
    assert not helper_panel.has_attr("open")
    assert toggle is not None
    assert toggle.has_attr("data-helper-toggle-affordance")
    assert _text(toggle.select_one(".helper-toggle-label-collapsed")) == "Click to show more"
    assert _text(toggle.select_one(".helper-toggle-label-expanded")) == "Click to hide"


def test_ui_retrieval_helper_toggle_affordance_uses_right_aligned_stable_hook_structure():
    css = _css_text()
    template = Path("app/templates/index.html").read_text(encoding="utf-8")

    assert 'class="helper-toggle-affordance"' in template
    assert 'data-helper-toggle-affordance' in template
    assert ".helper-toggle-affordance {" in css
    assert ".retrieval-helper-summary-main {\n  justify-content: space-between;\n}" in css


def test_ui_retrieval_helper_state_is_managed_only_in_js_session_storage():
    js = _js_text()

    assert 'const retrievalHelperStateKey = "local-secrets-manager.retrieval-helper-open";' in js
    assert 'window.sessionStorage.getItem(retrievalHelperStateKey)' in js
    assert 'retrievalHelperPanel.open = savedState === "true";' in js
    assert 'retrievalHelperPanel.addEventListener("toggle"' in js
    assert 'window.sessionStorage.setItem(retrievalHelperStateKey, String(retrievalHelperPanel.open));' in js
