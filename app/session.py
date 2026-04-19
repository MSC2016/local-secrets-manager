from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode


def now_utc() -> datetime:
    return datetime.now(UTC)


def sanitize_query_string(raw_query_string: str) -> str:
    if not raw_query_string:
        return ""

    sensitive_markers = {"passphrase", "secret", "value", "token", "password", "key"}
    sanitized_pairs = []
    for key, value in parse_qsl(raw_query_string, keep_blank_values=True):
        lowered = key.lower()
        sanitized_pairs.append((key, "[redacted]" if any(marker in lowered for marker in sensitive_markers) else value))
    return urlencode(sanitized_pairs)


@dataclass
class RuntimeLogEntry:
    timestamp: str
    level: str
    message: str
    remote_addr: str = ""
    method: str = ""
    path: str = ""
    status: int | None = None
    query_string: str = ""
    user_agent: str = ""

    @classmethod
    def create(
        cls,
        message: str,
        *,
        level: str = "info",
        remote_addr: str = "",
        method: str = "",
        path: str = "",
        status: int | None = None,
        query_string: str = "",
        user_agent: str = "",
    ) -> "RuntimeLogEntry":
        return cls(
            timestamp=now_utc().replace(microsecond=0).isoformat(),
            level=level,
            message=message,
            remote_addr=remote_addr,
            method=method,
            path=path,
            status=status,
            query_string=sanitize_query_string(query_string),
            user_agent=user_agent,
        )

    def request_target(self) -> str:
        if not self.path:
            return ""
        if self.query_string:
            return f"{self.path}?{self.query_string}"
        return self.path

    def rendered(self) -> str:
        parts = [self.timestamp, f"[{self.level}]"]
        if self.remote_addr:
            parts.append(self.remote_addr)
        if self.method:
            parts.append(self.method)
        request_target = self.request_target()
        if request_target:
            parts.append(request_target)
        if self.status is not None:
            parts.append(str(self.status))
        parts.append(self.message)
        return " ".join(parts)

    def search_text(self) -> str:
        return " ".join(
            part
            for part in [
                self.timestamp,
                self.level,
                self.remote_addr,
                self.method,
                self.request_target(),
                str(self.status) if self.status is not None else "",
                self.message,
                self.user_agent,
            ]
            if part
        ).lower()

    def as_dict(self) -> dict:
        rendered = self.rendered()
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "message": self.message,
            "remote_addr": self.remote_addr,
            "method": self.method,
            "path": self.path,
            "status": self.status,
            "query_string": self.query_string,
            "user_agent": self.user_agent,
            "rendered": rendered,
            "rendered_without_level": rendered.replace(f"[{self.level}] ", "", 1),
            "search_text": self.search_text(),
        }


@dataclass
class SessionState:
    unlocked_passphrase: str | None = None
    database_notice: str | None = None
    timeout_enabled: bool = True
    timeout_minutes: int = 15
    reset_on_read: bool = True
    lock_on_invalid_api_request: bool = True
    last_activity_at: datetime | None = None
    last_event: str = field(default_factory=lambda: RuntimeLogEntry.create("Service started in locked state.").rendered())
    events: list[RuntimeLogEntry] = field(default_factory=lambda: [RuntimeLogEntry.create("Service started in locked state.")])

    def log(
        self,
        event: str,
        *,
        level: str = "info",
        remote_addr: str = "",
        method: str = "",
        path: str = "",
        status: int | None = None,
        query_string: str = "",
        user_agent: str = "",
    ) -> RuntimeLogEntry:
        entry = RuntimeLogEntry.create(
            event,
            level=level,
            remote_addr=remote_addr,
            method=method,
            path=path,
            status=status,
            query_string=query_string,
            user_agent=user_agent,
        )
        self.last_event = entry.rendered()
        self.events.insert(0, entry)
        return entry

    def unlock(
        self,
        passphrase: str,
        event: str,
        *,
        level: str = "success",
        remote_addr: str = "",
        method: str = "",
        path: str = "",
        status: int | None = None,
        query_string: str = "",
        user_agent: str = "",
    ):
        self.unlocked_passphrase = passphrase
        self.last_activity_at = now_utc()
        self.database_notice = None
        self.log(
            event,
            level=level,
            remote_addr=remote_addr,
            method=method,
            path=path,
            status=status,
            query_string=query_string,
            user_agent=user_agent,
        )

    def lock(
        self,
        event: str,
        *,
        level: str = "warning",
        remote_addr: str = "",
        method: str = "",
        path: str = "",
        status: int | None = None,
        query_string: str = "",
        user_agent: str = "",
    ):
        self.unlocked_passphrase = None
        self.last_activity_at = None
        self.log(
            event,
            level=level,
            remote_addr=remote_addr,
            method=method,
            path=path,
            status=status,
            query_string=query_string,
            user_agent=user_agent,
        )

    def set_database_notice(self, message: str):
        self.database_notice = message

    def configure(self, *, timeout_enabled: bool, timeout_minutes: int, reset_on_read: bool, lock_on_invalid_api_request: bool):
        self.timeout_enabled = timeout_enabled
        self.timeout_minutes = timeout_minutes
        self.reset_on_read = reset_on_read
        self.lock_on_invalid_api_request = lock_on_invalid_api_request
        if self.unlocked_passphrase is not None:
            self.last_activity_at = now_utc()
        self.log("Session settings saved.")

    def touch(self):
        if self.unlocked_passphrase is not None:
            self.last_activity_at = now_utc()

    def seconds_remaining(self) -> int | None:
        if self.unlocked_passphrase is None:
            return 0
        if not self.timeout_enabled or self.last_activity_at is None:
            return None
        timeout_seconds = self.timeout_minutes * 60
        elapsed = int((now_utc() - self.last_activity_at).total_seconds())
        return max(timeout_seconds - elapsed, 0)

    def apply_timeout(self):
        if not self.timeout_enabled or self.unlocked_passphrase is None:
            return
        if self.seconds_remaining() == 0:
            self.lock("Auto-lock triggered after inactivity.", level="warning")

    def is_unlocked(self) -> bool:
        self.apply_timeout()
        return self.unlocked_passphrase is not None
