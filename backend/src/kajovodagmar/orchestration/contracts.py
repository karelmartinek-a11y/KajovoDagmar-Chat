from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

Intent = Literal[
    "conversation",
    "search",
    "read_memory",
    "read_history",
    "change_proposal",
    "confirmed_change",
    "memory_management",
    "history_management",
    "administration",
    "security_sensitive",
]

ToolName = Literal[
    "memory_search",
    "history_search",
    "memory_create",
    "memory_update",
    "memory_mark_outdated",
    "memory_delete",
    "memory_restore",
    "memory_merge",
    "history_continue",
    "history_delete",
    "history_restore",
    "none",
]


class MemoryProposal(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    category: Literal[
        "personal_fact", "preference", "rule", "decision", "commitment", "event", "note", "other"
    ]
    rationale: str = Field(min_length=1, max_length=500)
    event_at: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    source_message_id: str | None = None


class ToolCallDecision(BaseModel):
    name: ToolName
    arguments: dict[str, Any] = Field(default_factory=dict)


class SourceReference(BaseModel):
    source_type: Literal["memory", "history", "conversation", "application_state", "tool"]
    source_id: str
    label: str = Field(min_length=1, max_length=240)


class ModelDecision(BaseModel):
    intent: Intent
    result_type: Literal["answer", "clarification", "confirmation_required", "blocked"]
    answer: str = Field(min_length=1, max_length=50000)
    uncertainty: Literal["none", "low", "material"]
    sources: list[SourceReference] = Field(default_factory=list, max_length=20)
    tool_calls: list[ToolCallDecision] = Field(default_factory=list, max_length=5)
    memory_proposal: MemoryProposal | None = None
    requires_confirmation: bool = False

    @model_validator(mode="after")
    def validate_confirmation_consistency(self) -> ModelDecision:
        state_tools = [
            tool
            for tool in self.tool_calls
            if tool.name not in {"none", "memory_search", "history_search"}
        ]
        if state_tools and not self.requires_confirmation:
            raise ValueError("Stav měnící nástroj vyžaduje potvrzení.")
        if self.result_type == "confirmation_required" and not self.requires_confirmation:
            raise ValueError("Výsledek confirmation_required musí vyžadovat potvrzení.")
        if self.memory_proposal and not self.requires_confirmation:
            raise ValueError("Návrh paměti vyžaduje potvrzení.")
        return self
