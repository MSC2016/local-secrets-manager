from dataclasses import dataclass


@dataclass
class SecretSummary:
    name: str
    metadata: dict
    created_at: str
    updated_at: str
    last_accessed_at: str | None


class ServiceError(Exception):
    pass


class LockedError(ServiceError):
    pass


class NotFoundError(ServiceError):
    pass


class ValidationError(ServiceError):
    pass


class StorageError(ServiceError):
    pass
