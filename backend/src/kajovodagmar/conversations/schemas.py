from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ConversationStart(BaseModel):
    input_mode: Literal["voice", "text"] = "voice"
    language: str = Field(default="cs", min_length=2, max_length=16)
    continuation_of_id: UUID | None = None


class UserTurn(BaseModel):
    idempotency_key: str = Field(min_length=16, max_length=128)
    content: str = Field(min_length=1, max_length=50000)
    input_mode: Literal["voice", "text"]
    language: str = Field(default="cs", min_length=2, max_length=16)


class TranscriptCorrection(BaseModel):
    expected_message_version: int = Field(ge=1)
    corrected_content: str = Field(min_length=1, max_length=50000)
    request_new_answer: bool = False
