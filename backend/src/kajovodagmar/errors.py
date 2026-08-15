from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class DomainError(Exception):
    code: str
    message: str
    status_code: int = 400
    details: dict[str, Any] | None = None
    durable: bool = False


class ConflictError(DomainError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("conflict", message, 409, details)


class NotFoundError(DomainError):
    def __init__(self, message: str) -> None:
        super().__init__("not_found", message, 404)


class UnauthorizedError(DomainError):
    def __init__(self, message: str = "Přihlášení je vyžadováno.") -> None:
        super().__init__("unauthorized", message, 401, durable=True)


class CapabilityUnavailableError(DomainError):
    def __init__(self, capability: str, reason: str) -> None:
        super().__init__("capability_unavailable", reason, 503, {"capability": capability})
