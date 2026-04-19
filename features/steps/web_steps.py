import json
from datetime import timedelta
from urllib.parse import urlencode

from behave import given, then, when
from bs4 import BeautifulSoup

from app.session import now_utc


def _store_response(context, response):
    context.response = response
    content_type = response.headers.get("Content-Type", "")
    if "application/json" in content_type:
        context.json = response.get_json()
        context.page_text = json.dumps(context.json)
        context.last_event = ""
        context.merged_status = ""
        context.status_panel_open = False
        return

    html = response.get_data(as_text=True)
    context.soup = BeautifulSoup(html, "html.parser")
    context.page_text = context.soup.get_text(" ", strip=True)
    last_event = context.soup.select_one("#last-event")
    merged_status = context.soup.select_one("#merged-status")
    status_panel = context.soup.select_one("#status-panel")
    context.last_event = last_event.get_text(" ", strip=True) if last_event else ""
    context.merged_status = merged_status.get_text(" ", strip=True) if merged_status else ""
    context.status_panel_open = status_panel is not None and status_panel.has_attr("open")
    context.json = None


def _follow(context, response):
    if response.status_code in {301, 302, 303, 307, 308}:
        response = context.client.get(response.headers["Location"])
    _store_response(context, response)


@given("the web home page is open")
def step_open_home(context):
    _store_response(context, context.client.get("/"))


@when("the web home page is open")
def step_open_home_when(context):
    _store_response(context, context.client.get("/"))


@given('the service is unlocked with passphrase "{passphrase}"')
def step_unlock_service(context, passphrase):
    if context.service.status()["database_state"] != "ready":
        context.service.initialize_database(passphrase)
    ok, message = context.service.unlock(passphrase)
    assert ok, message


@given('the database is initialized with passphrase "{passphrase}"')
def step_initialize_database(context, passphrase):
    if context.service.status()["database_state"] != "ready":
        context.service.initialize_database(passphrase)


@given('a vault named "{vault}" exists')
def step_create_vault(context, vault):
    if context.service.status()["locked"]:
        ok, message = context.service.unlock("passphrase")
        assert ok, message
    existing = [item["name"] for item in context.service.list_vaults()]
    if vault not in existing:
        context.service.create_vault(vault)


@given('a secret "{secret}" exists in vault "{vault}" with value "{value}"')
def step_create_secret(context, secret, vault, value):
    if context.service.status()["locked"]:
        ok, message = context.service.unlock("passphrase")
        assert ok, message
    existing_vaults = [item["name"] for item in context.service.list_vaults()]
    if vault not in existing_vaults:
        context.service.create_vault(vault)
    existing_secrets = [item["name"] for item in context.service.list_secrets(vault)]
    if secret not in existing_secrets:
        context.service.create_secret(vault, secret, value, {})


@given('secret "{secret}" in vault "{vault}" has metadata key "{key}" with value "{value}"')
def step_set_metadata(context, secret, vault, key, value):
    if context.service.status()["locked"]:
        ok, message = context.service.unlock("passphrase")
        assert ok, message
    context.service.add_or_update_metadata(vault, secret, key, value)


@given('the vault "{vault}" is selected in the UI')
def step_open_selected_vault(context, vault):
    _store_response(context, context.client.get("/?" + urlencode({"vault": vault})))


@given("the session inactivity timer has expired")
def step_expire_timer(context):
    context.service.session.timeout_enabled = True
    context.service.session.timeout_minutes = 1
    context.service.session.last_activity_at = now_utc() - timedelta(minutes=2)


@given('the service has been initialized with passphrase "{passphrase}" and is now locked')
def step_initialized_and_locked(context, passphrase):
    if context.service.status()["database_state"] != "ready":
        context.service.initialize_database(passphrase)
    ok, message = context.service.unlock(passphrase)
    assert ok, message
    context.service.lock()


@when('I initialize the database with passphrase "{passphrase}" from the UI')
def step_initialize_database_ui(context, passphrase):
    response = context.client.post(
        "/database/initialize",
        data={"passphrase": passphrase, "confirm_passphrase": passphrase, "panel": "expanded"},
    )
    _follow(context, response)


@when('I change the passphrase from "{current_passphrase}" to "{new_passphrase}" from the UI')
def step_change_passphrase_ui(context, current_passphrase, new_passphrase):
    response = context.client.post(
        "/database/change-passphrase",
        data={
            "current_passphrase": current_passphrase,
            "new_passphrase": new_passphrase,
            "confirm_passphrase": new_passphrase,
            "panel": "expanded",
        },
    )
    _follow(context, response)


@when('I unlock with passphrase "{passphrase}"')
def step_unlock_via_ui(context, passphrase):
    response = context.client.post("/unlock", data={"passphrase": passphrase, "panel": "expanded"})
    _follow(context, response)


@when('I reset the database with confirmation "{confirmation}" and passphrase "{passphrase}" from the UI')
def step_reset_database_via_ui(context, confirmation, passphrase):
    response = context.client.post(
        "/database/reset",
        data={
            "confirmation": confirmation,
            "new_passphrase": passphrase,
            "confirm_passphrase": passphrase,
            "panel": "expanded",
        },
    )
    _follow(context, response)


@when("I unlock with an empty passphrase")
def step_unlock_empty_via_ui(context):
    response = context.client.post("/unlock", data={"passphrase": "", "panel": "expanded"})
    _follow(context, response)


@when("I lock the service from the UI")
def step_lock_via_ui(context):
    response = context.client.post("/lock", data={"panel": "expanded"})
    _follow(context, response)


@given("I lock the service from the UI")
def step_lock_via_ui_given(context):
    response = context.client.post("/lock", data={"panel": "expanded"})
    _follow(context, response)


@when('I save session settings with timeout_enabled "{timeout_enabled}", timeout_minutes "{timeout_minutes}", reset_on_read "{reset_on_read}"')
def step_save_settings(context, timeout_enabled, timeout_minutes, reset_on_read):
    data = {
        "selected_vault": "",
        "selected_secret": "",
        "timeout_minutes": timeout_minutes,
        "panel": "expanded",
    }
    if timeout_enabled == "on":
        data["timeout_enabled"] = "on"
    if reset_on_read == "on":
        data["reset_on_read"] = "on"
    response = context.client.post("/settings", data=data)
    _follow(context, response)


@when('I create a vault named "{vault}" from the UI')
def step_create_vault_ui(context, vault):
    response = context.client.post("/vaults/create", data={"name": vault})
    _follow(context, response)


@when('I rename vault "{current}" to "{new}" from the UI')
def step_rename_vault_ui(context, current, new):
    response = context.client.post("/vaults/rename", data={"current_name": current, "new_name": new})
    _follow(context, response)


@when('I delete vault "{vault}" from the UI')
def step_delete_vault_ui(context, vault):
    response = context.client.post("/vaults/delete", data={"name": vault})
    _follow(context, response)


@when('I create secret "{secret}" in vault "{vault}" with value "{value}" and metadata "{metadata}" from the UI')
def step_create_secret_ui(context, secret, vault, value, metadata):
    response = context.client.post(
        "/secrets/create",
        data={"vault": vault, "name": secret, "value": value, "metadata": metadata},
    )
    _follow(context, response)


@when('I create secret "{secret}" in vault "{vault}" with value "{value}" from the UI')
def step_create_secret_ui_without_metadata(context, secret, vault, value):
    response = context.client.post(
        "/secrets/create",
        data={"vault": vault, "name": secret, "value": value},
    )
    _follow(context, response)


@when('I rename secret "{current}" in vault "{vault}" to "{new}" from the UI')
def step_rename_secret_ui(context, current, vault, new):
    response = context.client.post(
        "/secrets/rename",
        data={"vault": vault, "current_name": current, "new_name": new},
    )
    _follow(context, response)


@when('I update secret "{secret}" in vault "{vault}" to value "{value}" from the UI')
def step_update_secret_ui(context, secret, vault, value):
    response = context.client.post(
        "/secrets/update",
        data={"vault": vault, "name": secret, "value": value},
    )
    _follow(context, response)


@when('I delete secret "{secret}" in vault "{vault}" from the UI')
def step_delete_secret_ui(context, secret, vault):
    response = context.client.post("/secrets/delete", data={"vault": vault, "name": secret})
    _follow(context, response)


@when('I set metadata key "{key}" to "{value}" for secret "{secret}" in vault "{vault}" from the UI')
def step_set_metadata_ui(context, key, value, secret, vault):
    response = context.client.post(
        "/metadata/set",
        data={"vault": vault, "secret_name": secret, "key": key, "value": value},
    )
    _follow(context, response)


@when('I delete metadata key "{key}" for secret "{secret}" in vault "{vault}" from the UI')
def step_delete_metadata_ui(context, key, secret, vault):
    response = context.client.post(
        "/metadata/delete",
        data={"vault": vault, "secret_name": secret, "key": key},
    )
    _follow(context, response)


@when("I confirm the metadata overwrite")
def step_confirm_metadata_overwrite(context):
    form = context.soup.select_one('form[data-editor-mode="metadata"]')
    assert form is not None
    response = context.client.post(
        "/metadata/set",
        data={
            "vault": form.select_one('input[name="vault"]').get("value", ""),
            "secret_name": form.select_one('input[name="secret_name"]').get("value", ""),
            "key": form.select_one('input[name="key"]').get("value", ""),
            "value": form.select_one('input[name="value"]').get("value", ""),
            "confirm_overwrite": form.select_one('input[name="confirm_overwrite"]').get("value", "1"),
            "expanded_secret": [item.get("value", "") for item in form.select('input[name="expanded_secret"]')],
        },
    )
    _follow(context, response)


@when("I cancel the metadata overwrite")
def step_cancel_metadata_overwrite(context):
    cancel_link = context.soup.select_one('form[data-editor-mode="metadata"] a[href]')
    assert cancel_link is not None
    _store_response(context, context.client.get(cancel_link.get("href")))


@when('I open the UI with query string "{query_string}"')
def step_open_query(context, query_string):
    _store_response(context, context.client.get("/?" + query_string))


@when("I open the UI again")
def step_open_home_again(context):
    _store_response(context, context.client.get("/"))


@when('I request the API path "{path}"')
def step_request_api(context, path):
    _store_response(context, context.client.get(path))


@then('the page shows status "{status_text}"')
def step_assert_status_text(context, status_text):
    assert status_text in context.page_text


@then('the last event says "{message}"')
def step_assert_last_event(context, message):
    assert context.last_event.endswith(message)


@then("the page has no top banner")
def step_assert_no_banner(context):
    assert context.soup.select_one(".banner") is None


@then('the merged status says "{message}"')
def step_assert_merged_status(context, message):
    assert context.merged_status == message


@then("the top status panel is collapsed")
def step_assert_status_panel_collapsed(context):
    assert context.status_panel_open is False


@then("the top status panel is expanded")
def step_assert_status_panel_expanded(context):
    assert context.status_panel_open is True


@then('the page contains text "{text}"')
def step_assert_page_contains(context, text):
    assert text in context.page_text


@then('the page does not contain text "{text}"')
def step_assert_page_not_contains(context, text):
    assert text not in context.page_text


@then('the timeout input value is "{value}"')
def step_assert_timeout_input_value(context, value):
    timeout_input = context.soup.select_one('input[name="timeout_minutes"]')
    assert timeout_input is not None
    assert timeout_input.get("value") == value


@then('the page contains a password input named "{field_name}"')
def step_assert_password_input(context, field_name):
    element = context.soup.select_one(f'input[name="{field_name}"][type="password"]')
    assert element is not None


@then('the API response status is {status_code:d}')
def step_assert_status_code(context, status_code):
    assert context.response.status_code == status_code


@then('the JSON field "{field}" equals "{value}"')
def step_assert_json_field(context, field, value):
    assert str(context.json[field]) == value


@then('the JSON field "{field}" is true')
def step_assert_json_true(context, field):
    assert context.json[field] is True


@then('the JSON field "{field}" is false')
def step_assert_json_false(context, field):
    assert context.json[field] is False


@then('the JSON field "{field}" is absent')
def step_assert_json_field_absent(context, field):
    assert field not in context.json


@then('vault "{vault}" exists in storage')
def step_assert_vault_exists(context, vault):
    assert vault in [item["name"] for item in context.service.list_vaults()]


@then('vault "{vault}" does not exist in storage')
def step_assert_vault_missing(context, vault):
    assert vault not in [item["name"] for item in context.service.list_vaults()]


@then('secret "{secret}" exists in vault "{vault}"')
def step_assert_secret_exists(context, secret, vault):
    assert secret in [item["name"] for item in context.service.list_secrets(vault)]


@then('secret "{secret}" does not exist in vault "{vault}"')
def step_assert_secret_missing(context, secret, vault):
    assert secret not in [item["name"] for item in context.service.list_secrets(vault)]


@then('secret "{secret}" in vault "{vault}" has value "{value}"')
def step_assert_secret_value(context, secret, vault, value):
    assert context.service.read_secret(vault, secret)["value"] == value


@then('secret "{secret}" in vault "{vault}" has metadata key "{key}" with value "{value}"')
def step_assert_metadata_value(context, secret, vault, key, value):
    assert context.service.read_secret(vault, secret)["metadata"][key] == value


@then('secret "{secret}" in vault "{vault}" does not have metadata key "{key}"')
def step_assert_metadata_missing(context, secret, vault, key):
    assert key not in context.service.read_secret(vault, secret)["metadata"]


@then('the selected vault shown is "{vault}"')
def step_assert_selected_vault_text(context, vault):
    assert f"Secrets In {vault}" in context.page_text


@then('the helper path "{path}" is shown')
def step_assert_helper_path(context, path):
    assert path in context.page_text


@then('the helper snippet contains "{text}"')
def step_assert_helper_snippet(context, text):
    assert text in context.page_text


@then('overwrite confirmation is shown for metadata key "{key}" from value "{old_value}" to value "{new_value}"')
def step_assert_metadata_overwrite_confirmation(context, key, old_value, new_value):
    warning = context.soup.select_one("#metadata-overwrite-warning")
    assert warning is not None
    warning_text = warning.get_text(" ", strip=True)
    assert f'Metadata key "{key}" already exists.' in warning_text
    assert "Overwrite existing value?" in warning_text
    assert f"Old: {old_value}" in warning_text
    assert f"New: {new_value}" in warning_text


@then("overwrite confirmation is not shown")
def step_assert_metadata_overwrite_not_shown(context):
    assert context.soup.select_one("#metadata-overwrite-warning") is None


@then('the log contains text "{text}"')
def step_assert_log_contains(context, text):
    assert text in context.page_text


@then('unlocking with passphrase "{passphrase}" succeeds in service state')
def step_assert_service_unlock(context, passphrase):
    ok, message = context.service.unlock(passphrase)
    assert ok, message


@then('unlocking with passphrase "{passphrase}" fails with message "{message}"')
def step_assert_service_unlock_failure(context, passphrase, message):
    ok, actual_message = context.service.unlock(passphrase)
    assert ok is False
    assert actual_message == message
