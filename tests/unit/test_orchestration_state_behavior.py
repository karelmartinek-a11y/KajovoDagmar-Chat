from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from kajovodagmar.audit.service import AuditContext
from kajovodagmar.db.models import Conversation, ConversationMessage, OrchestrationRun
from kajovodagmar.errors import ConflictError, DomainError, NotFoundError
from kajovodagmar.orchestration.contracts import ModelDecision, ToolCallDecision
from kajovodagmar.orchestration.service import OrchestrationService
from kajovodagmar.providers.contracts import ChatResult


class Rows:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def all(self) -> list[Any]:
        return self.values


class Session:
    def __init__(
        self,
        *,
        scalars: list[Any] | None = None,
        rows: list[list[Any]] | None = None,
        gets: list[Any] | None = None,
    ) -> None:
        self.scalar_values = scalars or []
        self.row_values = rows or []
        self.get_values = gets or []
        self.added: list[Any] = []

    async def scalar(self, _query: Any) -> Any:
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _query: Any) -> Rows:
        return Rows(self.row_values.pop(0) if self.row_values else [])

    async def get(self, *_args: Any, **_kwargs: Any) -> Any:
        return self.get_values.pop(0) if self.get_values else None

    def add(self, value: Any) -> None:
        self.added.append(value)
        if getattr(value, "id", None) is None:
            value.id = uuid4()
        if getattr(value, "version", None) is None:
            value.version = 1

    async def flush(self) -> None:
        return None


def service() -> Any:
    return OrchestrationService(
        cast(Any, SimpleNamespace(runtime=AsyncMock())),
        cast(Any, SimpleNamespace(add_assistant_turn=AsyncMock())),
        cast(Any, SimpleNamespace()),
        cast(Any, SimpleNamespace()),
        cast(Any, SimpleNamespace()),
        cast(Any, SimpleNamespace(append=AsyncMock())),
    )


def decision(**changes: Any) -> ModelDecision:
    value: dict[str, Any] = {
        "intent": "conversation",
        "result_type": "answer",
        "answer": "Ověřená odpověď.",
        "uncertainty": "none",
        "sources": [],
        "tool_calls": [],
        "requires_confirmation": False,
    }
    value.update(changes)
    return ModelDecision.model_validate(value)


def conversation_context() -> tuple[Any, Any, Any, Any]:
    account_id = uuid4()
    conversation = Conversation(
        id=uuid4(), account_id=account_id, state="active", language="cs"
    )
    message = ConversationMessage(
        id=uuid4(),
        conversation_id=conversation.id,
        sequence=1,
        role="user",
        content="Zapamatuj si modrou",
        input_mode="text",
        status="final",
        idempotency_key="orchestration-state-0001",
    )
    run = OrchestrationRun(
        id=uuid4(),
        account_id=account_id,
        conversation_id=conversation.id,
        source_message_id=message.id,
        state="running",
        orchestration_version="1",
        prompt_version="1",
        context_manifest={},
        usage={},
    )
    return account_id, conversation, message, run


@pytest.mark.asyncio
async def test_action_creation_confirmation_requirement_and_memory_proposal() -> None:
    orchestration = service()
    account_id, conversation, message, run = conversation_context()
    assert (
        await orchestration._create_actions(
            cast(Any, Session()),
            run=run,
            account_id=account_id,
            conversation=conversation,
            source_message=message,
            decision=decision(),
        )
        == []
    )
    proposal = decision(
        result_type="confirmation_required",
        requires_confirmation=True,
        memory_proposal={
            "content": "Oblíbená barva je modrá",
            "category": "preference",
            "rationale": "Výslovný požadavek.",
        },
    )
    actions = await orchestration._create_actions(
        cast(Any, Session()),
        run=run,
        account_id=account_id,
        conversation=conversation,
        source_message=message,
        decision=proposal,
    )
    assert actions[0].name == "memory_create"
    assert actions[0].state == "pending_confirmation"
    assert len(actions[0].arguments_hash) == 64

    unsafe = decision()
    unsafe.tool_calls = [
        ToolCallDecision(
            name="memory_create", arguments={"content": "Fakt", "category": "note"}
        )
    ]
    with pytest.raises(DomainError, match="povinné potvrzení"):
        await orchestration._create_actions(
            cast(Any, Session()),
            run=run,
            account_id=account_id,
            conversation=conversation,
            source_message=message,
            decision=unsafe,
        )


@pytest.mark.asyncio
async def test_action_confirmation_guards_success_and_failure() -> None:
    orchestration = service()
    account_id = uuid4()
    context = AuditContext("administrator", account_id)
    with pytest.raises(NotFoundError):
        await orchestration.confirm_action(
            cast(Any, Session()),
            account_id=account_id,
            action_id=uuid4(),
            expected_action_version=1,
            context=context,
        )
    completed = SimpleNamespace(state="completed")
    assert (
        await orchestration.confirm_action(
            cast(Any, Session(scalars=[completed])),
            account_id=account_id,
            action_id=uuid4(),
            expected_action_version=1,
            context=context,
        )
        is completed
    )
    action = SimpleNamespace(
        id=uuid4(),
        run_id=uuid4(),
        name="memory_create",
        state="pending_confirmation",
        version=2,
        expires_at=None,
        result=None,
        confirmed_at=None,
        completed_at=None,
        error_code=None,
    )
    with pytest.raises(ConflictError, match="změněn"):
        await orchestration.confirm_action(
            cast(Any, Session(scalars=[action])),
            account_id=account_id,
            action_id=action.id,
            expected_action_version=1,
            context=context,
        )
    action.state = "cancelled"
    with pytest.raises(ConflictError, match="stavu"):
        await orchestration.confirm_action(
            cast(Any, Session(scalars=[action])),
            account_id=account_id,
            action_id=action.id,
            expected_action_version=2,
            context=context,
        )
    action.state = "pending_confirmation"
    action.expires_at = datetime.now(timezone.utc)
    with pytest.raises(ConflictError, match="vypršela"):
        await orchestration.confirm_action(
            cast(Any, Session(scalars=[action])),
            account_id=account_id,
            action_id=action.id,
            expected_action_version=2,
            context=context,
        )
    assert action.state == "expired"

    action.state = "pending_confirmation"
    action.version = 1
    action.expires_at = None
    orchestration._execute_state_action = AsyncMock(return_value={"ok": True})
    run = SimpleNamespace(id=action.run_id, state="awaiting_confirmation", version=1)
    confirmed = await orchestration.confirm_action(
        cast(Any, Session(scalars=[action, None], gets=[run])),
        account_id=account_id,
        action_id=action.id,
        expected_action_version=1,
        context=context,
    )
    assert confirmed.state == "completed"
    assert run.state == "completed"

    failed = SimpleNamespace(
        id=uuid4(),
        run_id=uuid4(),
        name="memory_create",
        state="pending_confirmation",
        version=1,
        expires_at=None,
        error_code=None,
    )
    orchestration._execute_state_action = AsyncMock(
        side_effect=DomainError("execution_failed", "Selhání", 409)
    )
    with pytest.raises(DomainError):
        await orchestration.confirm_action(
            cast(Any, Session(scalars=[failed])),
            account_id=account_id,
            action_id=failed.id,
            expected_action_version=1,
            context=context,
        )
    assert failed.state == "failed"
    assert failed.error_code == "execution_failed"


@pytest.mark.asyncio
async def test_cancel_run_and_answer_guards() -> None:
    orchestration = service()
    account_id, conversation, message, _ = conversation_context()
    context = AuditContext("administrator", account_id)
    with pytest.raises(NotFoundError):
        await orchestration.cancel_run(
            cast(Any, Session()),
            account_id=account_id,
            run_id=uuid4(),
            context=context,
        )
    terminal = SimpleNamespace(state="completed")
    assert (
        await orchestration.cancel_run(
            cast(Any, Session(scalars=[terminal])),
            account_id=account_id,
            run_id=uuid4(),
            context=context,
        )
        is terminal
    )
    pending_action = SimpleNamespace(state="pending_confirmation", version=1)
    active_run = SimpleNamespace(
        id=uuid4(), state="running", cancelled_at=None, version=1
    )
    cancelled = await orchestration.cancel_run(
        cast(Any, Session(scalars=[active_run], rows=[[pending_action]])),
        account_id=account_id,
        run_id=active_run.id,
        context=context,
    )
    assert cancelled.state == "cancelled"
    assert pending_action.state == "cancelled"

    with pytest.raises(NotFoundError, match="Konverzace"):
        await orchestration.answer(
            cast(Any, Session(scalars=[None, None])),
            account_id,
            conversation.id,
            message.id,
        )
    for state in ("running", "awaiting_confirmation"):
        processing = SimpleNamespace(state=state, id=uuid4())
        with pytest.raises(ConflictError, match="již zpracovává"):
            await orchestration.answer(
                cast(Any, Session(scalars=[processing])),
                account_id,
                conversation.id,
                message.id,
            )
    other = ConversationMessage(
        id=uuid4(),
        conversation_id=conversation.id,
        sequence=2,
        role="assistant",
        content="Jiná zpráva",
        input_mode="generated",
        status="final",
        idempotency_key="orchestration-other-0001",
    )
    with pytest.raises(NotFoundError, match="Zdrojová"):
        await orchestration.answer(
            cast(
                Any,
                Session(
                    scalars=[None, conversation],
                    rows=[[other]],
                ),
            ),
            account_id,
            conversation.id,
            message.id,
        )


@pytest.mark.asyncio
async def test_answer_read_tool_success_loop_protection_and_failure() -> None:
    orchestration = service()
    account_id, conversation, message, _ = conversation_context()
    provider, model = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
    bundle = SimpleNamespace(
        prompt="prompt", manifest={"source": "test"}, allowed_source_ids=frozenset()
    )
    read_decision = decision(
        tool_calls=[{"name": "memory_search", "arguments": {"query": "dotaz"}}]
    )
    final_decision = decision()
    first_result = ChatResult("first", "", read_decision.model_dump(), 4, 2)
    second_result = ChatResult("second", "", final_decision.model_dump(), 3, 1)
    response = ConversationMessage(
        id=uuid4(),
        conversation_id=conversation.id,
        sequence=2,
        role="assistant",
        content=final_decision.answer,
        input_mode="generated",
        status="final",
        idempotency_key="orchestration-response-0001",
    )
    orchestration._primary_model = AsyncMock(return_value=(provider, model))
    orchestration._build_context = AsyncMock(return_value=bundle)
    orchestration._call_model = AsyncMock(
        side_effect=[(read_decision, first_result), (final_decision, second_result)]
    )
    orchestration._execute_read_tools = AsyncMock(
        return_value=([{"tool": "memory_search", "items": []}], set())
    )
    orchestration._create_actions = AsyncMock(return_value=[])
    orchestration.conversations.add_assistant_turn.return_value = response
    session = Session(scalars=[None, conversation], rows=[[message]])
    result = await orchestration.answer(
        cast(Any, session), account_id, conversation.id, message.id
    )
    assert result.message is response
    run = next(row for row in session.added if isinstance(row, OrchestrationRun))
    assert run.state == "completed"
    assert run.usage == {"input_units": 7, "output_units": 3}

    orchestration._call_model = AsyncMock(
        side_effect=[
            (read_decision, first_result),
            (read_decision, first_result),
        ]
    )
    with pytest.raises(DomainError, match="znovu požadoval"):
        await orchestration.answer(
            cast(Any, Session(scalars=[None, conversation], rows=[[message]])),
            account_id,
            conversation.id,
            message.id,
        )

    orchestration._call_model = AsyncMock(
        side_effect=DomainError("provider", "Nedostupný", 503)
    )
    failed_session = Session(scalars=[None, conversation], rows=[[message]])
    with pytest.raises(DomainError):
        await orchestration.answer(
            cast(Any, failed_session), account_id, conversation.id, message.id
        )
    failed_run = next(
        row for row in failed_session.added if isinstance(row, OrchestrationRun)
    )
    assert failed_run.state == "failed"
