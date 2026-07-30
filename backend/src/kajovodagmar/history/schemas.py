from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class HistorySearch(BaseModel):
    query: str = Field(default="", max_length=500)
    states: list[str] = Field(default_factory=lambda: ["completed", "interrupted", "recovered"])
    from_at: datetime | None = None
    to_at: datetime | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class MetadataUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    summary: str | None = Field(default=None, min_length=1, max_length=10000)
