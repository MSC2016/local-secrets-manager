from __future__ import annotations

from flask import has_request_context, request, url_for


def merged_status_text(status: dict) -> str:
    database_label = {
        "ready": "Ready",
        "missing": "Setup required",
        "uninitialized": "Setup required",
        "corrupted": "Corrupted database",
    }.get(status["database_state"], status["database_state"].replace("_", " ").capitalize())
    session_label = "Unlocked" if status["unlocked"] else "Locked"
    return f"{session_label} · {database_label}"



def coerce_expanded_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = [value]
    else:
        candidates = list(value)

    expanded: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        for part in str(candidate).split(","):
            name = part.strip()
            if name and name not in seen:
                seen.add(name)
                expanded.append(name)
    return expanded



def expanded_values_from_request(source) -> list[str]:
    values = []
    if hasattr(source, "getlist"):
        values.extend(source.getlist("expanded"))
        values.extend(source.getlist("expanded_secret"))
    return coerce_expanded_list(values)



def merged_expanded_list(current, *extra) -> list[str]:
    return coerce_expanded_list([*(coerce_expanded_list(current)), *extra])



def build_home_url(**params) -> str:
    filtered = {}
    for key, value in params.items():
        if key == "expanded":
            expanded_values = coerce_expanded_list(value)
            if expanded_values:
                filtered[key] = expanded_values
        elif value:
            filtered[key] = value
    return url_for("web.home", **filtered)



def current_panel_state() -> str | None:
    panel = request.values.get("panel", "").strip().lower()
    return "expanded" if panel == "expanded" else None



def request_log_details() -> dict:
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
