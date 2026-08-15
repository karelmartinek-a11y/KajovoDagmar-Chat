from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ConversationStart(BaseModel):
    input_mode: Literal["voice", "text"] = "voice"
    language: str = Field(default="cs", min_length=2, max_length=16)
    continuation_of_id: UUID | None = None


class UserTurn(BaseModel):
    idempotency_key: str = Field(min_length=16, max_length=128)
    content: str = Field(min_length=1, max_length=50000)
    input_mode: Literal["voice", "text"]
    language: str = Field(default="cs", min_length=2, max_length=16)

    @field_validator("content", mode="before")
    @classmethod
    def non_blank_content(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Replika nesmí být prázdná.")
        return value.strip()


class TranscriptCorrection(BaseModel):
    expected_message_version: int = Field(ge=1)
    corrected_content: str = Field(min_length=1, max_length=50000)
    request_new_answer: bool = False

    @field_validator("corrected_content", mode="before")
    @classmethod
    def non_blank_correction(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Opravená replika nesmí být prázdná.")
        return value.strip()
