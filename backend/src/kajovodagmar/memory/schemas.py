from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

MemoryCategory = Literal[
    "personal_fact", "preference", "rule", "decision", "commitment", "event", "note", "other"
]


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    category: MemoryCategory
    origin_type: Literal["explicit_command", "manual", "assistant_suggestion"]
    source_conversation_id: UUID | None = None
    source_message_id: UUID | None = None
    original_expression: str | None = Field(default=None, max_length=10000)
    event_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    keywords: list[str] = Field(default_factory=list, max_length=30)
    confirmed: bool = False

    @field_validator("content", mode="before")
    @classmethod
    def non_blank_content(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Obsah paměti nesmí být prázdný.")
        return value.strip()


class MemoryUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    content: str | None = Field(default=None, min_length=1, max_length=10000)
    category: MemoryCategory | None = None
    event_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    mark_outdated: bool = False

    @field_validator("content", mode="before")
    @classmethod
    def non_blank_content(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Obsah paměti nesmí být prázdný.")
        return value.strip()


class MemorySearch(BaseModel):
    query: str = Field(default="", max_length=500)
    categories: list[MemoryCategory] = Field(default_factory=list)
    states: list[str] = Field(default_factory=lambda: ["active"])
    from_at: datetime | None = None
    to_at: datetime | None = None
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None
