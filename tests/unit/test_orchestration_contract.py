from __future__ import annotations

import pytest
from pydantic import ValidationError

from kajovodagmar.orchestration.contracts import ModelDecision


def test_structured_decision_requires_explicit_uncertainty() -> None:
    decision = ModelDecision.model_validate(
        {
            "intent": "conversation",
            "result_type": "answer",
            "answer": "Doložená odpověď.",
            "uncertainty": "none",
            "sources": [],
            "tool_calls": [],
            "requires_confirmation": False,
        }
    )
    assert decision.answer == "Doložená odpověď."


def test_invalid_result_cannot_execute() -> None:
    with pytest.raises(ValidationError):
        ModelDecision.model_validate(
            {
                "intent": "conversation",
                "result_type": "answer",
                "answer": "",
                "uncertainty": "unknown",
            }
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "tool_calls": [{"name": "memory_create", "arguments": {}}],
            "requires_confirmation": False,
        },
        {
            "result_type": "confirmation_required",
            "requires_confirmation": False,
        },
        {
            "memory_proposal": {
                "content": "Důležitá preference",
                "category": "preference",
                "rationale": "Uživatel ji výslovně uvedl.",
            },
            "requires_confirmation": False,
        },
    ],
)
def test_state_changes_always_require_confirmation(payload: dict[str, object]) -> None:
    base: dict[str, object] = {
        "intent": "conversation",
        "result_type": "answer",
        "answer": "Bez změny stavu.",
        "uncertainty": "none",
        "sources": [],
        "tool_calls": [],
        "requires_confirmation": False,
    }
    with pytest.raises(ValidationError):
        ModelDecision.model_validate(base | payload)
