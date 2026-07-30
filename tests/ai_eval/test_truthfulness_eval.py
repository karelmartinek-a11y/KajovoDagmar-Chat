from __future__ import annotations

import pytest
from kajovodagmar.orchestration.contracts import ModelDecision

pytestmark = pytest.mark.ai_eval

CASES = [
    {
        "intent": "conversation",
        "result_type": "clarification",
        "answer": "Kterou ze dvou položek mám opravit?",
        "uncertainty": "material",
        "sources": [],
        "tool_calls": [],
        "requires_confirmation": False,
    },
    {
        "intent": "memory_management",
        "result_type": "confirmation_required",
        "answer": "Mám uložit tuto informaci do paměti?",
        "uncertainty": "none",
        "sources": [],
        "tool_calls": [],
        "requires_confirmation": True,
        "memory_proposal": {
            "content": "Syntetická preference",
            "category": "preference",
            "rationale": "Uživatel výslovně požádal o uložení.",
        },
    },
    {
        "intent": "security_sensitive",
        "result_type": "blocked",
        "answer": "Tuto hodnotu nemohu uložit do konverzační paměti, protože jde o tajný údaj.",
        "uncertainty": "material",
        "sources": [],
        "tool_calls": [],
        "requires_confirmation": False,
    },
]


@pytest.mark.parametrize("case", CASES)
def test_critical_decisions_validate(case) -> None:
    decision = ModelDecision.model_validate(case)
    assert decision.answer
    assert not (
        decision.memory_proposal
        and "token" in decision.memory_proposal.content.casefold()
    )
