from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ExportRequest(BaseModel):
    kind: Literal["history", "memory", "configuration", "audit"]
    format: Literal["json", "markdown"]
    scope: dict[str, Any] = Field(default_factory=lambda: {"all": True})
