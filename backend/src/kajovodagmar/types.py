from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import NewType
from uuid import UUID, uuid4

UserId = NewType("UserId", UUID)
ConversationId = NewType("ConversationId", UUID)
MemoryId = NewType("MemoryId", UUID)


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> UUID:
    return uuid4()


class AccountState(StrEnum):
    UNINITIALIZED = "uninitialized"
    ACTIVE = "active"
    TEMPORARILY_RESTRICTED = "temporarily_restricted"
    RECOVERY = "recovery"


class ConversationState(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    RECOVERED = "recovered"
    DELETED = "deleted"


class MemoryState(StrEnum):
    PENDING = "pending_confirmation"
    ACTIVE = "active"
    OUTDATED = "outdated"
    MERGED = "merged"
    DELETED = "deleted"


class VoiceState(StrEnum):
    READY = "ready"
    CONNECTING = "connecting"
    LISTENING = "listening"
    PROCESSING = "processing"
    RESPONDING = "responding"
    PAUSED = "paused"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    ENDED = "ended"
