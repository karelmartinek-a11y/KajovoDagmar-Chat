from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from kajovodagmar.audit.service import AuditContext
from kajovodagmar.db.models import (
    Conversation,
    ConversationMessage,
    MemoryItem,
    ModelCatalogEntry,
    OrchestrationRun,
    ProviderConfiguration,
    ToolAction,
)
from kajovodagmar.errors import (
    CapabilityUnavailableError,
    ConflictError,
    DomainError,
    NotFoundError,
)
from kajovodagmar.orchestration.contracts import ModelDecision, ToolCallDecision
from kajovodagmar.orchestration.service import OrchestrationService
from kajovodagmar.providers.contracts import ChatResult


class ScalarRows:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows


class FakeSession:
    def __init__(
        self,
        *,
        scalar_values: list[Any] | None = None,
        scalar_rows: list[list[Any]] | None = None,
        get_values: list[Any] | None = None,
    ) -> None:
        self.scalar_values = scalar_values or []
        self.scalar_rows = scalar_rows or []
        self.get_values = get_values or []
        self.added: list[Any] = []

    async def scalar(self, _query: Any) -> Any:
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _query: Any) -> ScalarRows:
        return ScalarRows(self.scalar_rows.pop(0) if self.scalar_rows else [])

    async def get(self, *_args: Any, **_kwargs: Any) -> Any:
        return self.get_values.pop(0) if self.get_values else None

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


def service() -> Any:
    return OrchestrationService(
        cast(Any, SimpleNamespace(runtime=AsyncMock())),
        cast(Any, SimpleNamespace(add_assistant_turn=AsyncMock())),
        cast(
            Any,
            SimpleNamespace(
                get=AsyncMock(),
                create=AsyncMock(),
                update=AsyncMock(),
                soft_delete=AsyncMock(),
                restore=AsyncMock(),
                merge=AsyncMock(),
                search=AsyncMock(),
            ),
        ),
        cast(
            Any,
            SimpleNamespace(
                detail=AsyncMock(),
                continue_from=AsyncMock(),
                soft_delete=AsyncMock(),
                restore=AsyncMock(),
                search=AsyncMock(),
            ),
        ),
        cast(Any, SimpleNamespace(ranked_owner_ids=AsyncMock(return_value=[]))),
        cast(Any, SimpleNamespace(append=AsyncMock())),
    )


def decision(**overrides: Any) -> ModelDecision:
    payload: dict[str, Any] = {
        "intent": "conversation",
        "result_type": "answer",
        "answer": "Ověřená odpověď.",
        "uncertainty": "none",
        "sources": [],
        "tool_calls": [],
        "requires_confirmation": False,
    }
    payload.update(overrides)
    return ModelDecision.model_validate(payload)


def digest(arguments: dict[str, Any]) -> str:
    encoded = json.dumps(
        arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


@pytest.mark.asyncio
async def test_model_call_records_success_and_contract_failure() -> None:
    orchestration = service()
    valid = decision()
    provider = SimpleNamespace(
        chat=AsyncMock(
            return_value=ChatResult(
                "response-1", valid.answer, valid.model_dump(), 12, 7
            )
        )
    )
    orchestration.providers.runtime.return_value = provider
    session = FakeSession()
    run = OrchestrationRun(
        id=uuid4(),
        account_id=uuid4(),
        conversation_id=uuid4(),
        source_message_id=uuid4(),
        provider_id=uuid4(),
        model_id=uuid4(),
        state="running",
        orchestration_version="1",
        prompt_version="1",
        context_manifest={},
        usage={},
        attempt_count=0,
    )
    provider_row = ProviderConfiguration(
        id=run.provider_id,
        provider_type="openai_compatible",
        display_name="Test",
        base_url="https://provider.invalid",
        enabled=True,
        verification_state="verified",
        capabilities={},
    )
    model = ModelCatalogEntry(
        id=run.model_id,
        provider_id=provider_row.id,
        external_id="chat-model",
        display_name="Chat",
        role="conversation",
        capabilities={"chat": True},
        available=True,
    )
    parsed, result = await orchestration._call_model(
        cast(Any, session), run, provider_row, model, "prompt", [], temperature=0.1
    )
    assert parsed.answer == valid.answer
    assert result.provider_response_id == "response-1"
    assert run.attempt_count == 1
    assert session.added[0].state == "completed"

    provider.chat.return_value = ChatResult("bad", "", {"answer": 1}, None, None)
    with pytest.raises(DomainError, match="interní kontrakt"):
        await orchestration._call_model(
            cast(Any, session), run, provider_row, model, "prompt", [], temperature=0.1
        )
    assert session.added[-1].state == "failed"
    assert session.added[-1].error_code == "model_decision_invalid"


@pytest.mark.asyncio
async def test_context_bundle_contains_ranked_memory_sources_and_tool_evidence() -> (
    None
):
    orchestration = service()
    account_id = uuid4()
    conversation = Conversation(
        id=uuid4(),
        account_id=account_id,
        state="active",
        language="cs",
        context_summary="Souhrn",
    )
    first = ConversationMessage(
        id=uuid4(),
        conversation_id=conversation.id,
        sequence=1,
        role="user",
        content="První zpráva",
        status="final",
        input_mode="text",
        idempotency_key="context-message-0001",
    )
    memory = MemoryItem(
        id=uuid4(),
        account_id=account_id,
        category="note",
        content="Ověřená paměť",
        state="active",
        origin_type="explicit_command",
    )
    source = SimpleNamespace(
        memory_id=memory.id,
        source_type="conversation",
        conversation_id=conversation.id,
        message_id=first.id,
    )
    orchestration.search.ranked_owner_ids.return_value = [memory.id]
    session = FakeSession(
        scalar_values=[SimpleNamespace(value={"value": "concise"})],
        scalar_rows=[[memory], [source]],
    )
    bundle = await orchestration._build_context(
        cast(Any, session),
        account_id=account_id,
        conversation=conversation,
        messages=[first],
        source_message=first,
        normalized_input="dotaz",
        tool_results=[{"tool": "memory_search", "items": [{"id": str(memory.id)}]}],
    )
    assert "Ověřená paměť" in bundle.prompt
    assert "concise" in bundle.prompt
    assert str(memory.id) in bundle.allowed_source_ids
    assert bundle.manifest["classes"][-1] == "verified_tool_result"

    orchestration.search.ranked_owner_ids.return_value = []
    empty = FakeSession(scalar_values=[None], scalar_rows=[[]])
    fallback = await orchestration._build_context(
        cast(Any, empty),
        account_id=account_id,
        conversation=conversation,
        messages=[first],
        source_message=first,
        normalized_input="dotaz",
        tool_results=[],
    )
    assert "Žádný nástroj nebyl spuštěn." in fallback.prompt


@pytest.mark.asyncio
async def test_read_tools_search_memory_history_and_reject_empty_query() -> None:
    orchestration = service()
    now = datetime.now(timezone.utc)
    memory = SimpleNamespace(
        id=uuid4(), content="Paměť", category="note", state="active", event_at=None
    )
    history = SimpleNamespace(
        id=uuid4(), title="Historie", summary="Souhrn", started_at=now, state="closed"
    )
    orchestration.search.ranked_owner_ids.side_effect = [[memory.id], [history.id]]
    orchestration.memory.search.return_value = [memory]
    orchestration.history.search.return_value = [history]
    results, source_ids = await orchestration._execute_read_tools(
        cast(Any, FakeSession()),
        uuid4(),
        [
            ToolCallDecision(
                name="memory_search", arguments={"query": " paměť ", "limit": 99}
            ),
            ToolCallDecision(
                name="history_search", arguments={"query": "historie", "limit": 0}
            ),
        ],
    )
    assert [row["tool"] for row in results] == ["memory_search", "history_search"]
    assert source_ids == {str(memory.id), str(history.id)}
    with pytest.raises(DomainError, match="platný dotaz"):
        await orchestration._execute_read_tools(
            cast(Any, FakeSession()),
            uuid4(),
            [ToolCallDecision(name="memory_search", arguments={"query": " "})],
        )


@pytest.mark.asyncio
async def test_action_normalization_covers_memory_and_history_variants() -> None:
    orchestration = service()
    account_id = uuid4()
    conversation = Conversation(
        id=uuid4(), account_id=account_id, state="active", language="cs"
    )
    source_message = ConversationMessage(
        id=uuid4(),
        conversation_id=conversation.id,
        sequence=1,
        role="user",
        content="Zapamatuj si to",
        status="final",
        input_mode="text",
        idempotency_key="normalize-action-0001",
    )
    normalized, preview, expected = await orchestration._normalize_action(
        cast(Any, FakeSession()),
        account_id,
        ToolCallDecision(
            name="memory_create",
            arguments={"content": "  Česká   věta ", "category": "note"},
        ),
        conversation,
        source_message,
    )
    assert normalized["content"] == "Česká věta"
    assert preview["operation"] == "Uložit paměť"
    assert expected is None

    item = SimpleNamespace(id=uuid4(), version=3, content="Původní", state="active")
    orchestration.memory.get.return_value = item
    normalized, preview, expected = await orchestration._normalize_action(
        cast(Any, FakeSession()),
        account_id,
        ToolCallDecision(
            name="memory_update",
            arguments={
                "memory_id": str(item.id),
                "expected_version": 3,
                "content": "Nová",
            },
        ),
        conversation,
        source_message,
    )
    assert normalized["content"] == "Nová"
    assert preview["target"] == "Původní"
    assert expected == 3
    with pytest.raises(ConflictError):
        await orchestration._normalize_action(
            cast(Any, FakeSession()),
            account_id,
            ToolCallDecision(
                name="memory_delete",
                arguments={"memory_id": str(item.id), "expected_version": 2},
            ),
            conversation,
            source_message,
        )

    one, two = (
        SimpleNamespace(id=uuid4(), version=1, content="Jedna"),
        SimpleNamespace(id=uuid4(), version=2, content="Dvě"),
    )
    with pytest.raises(DomainError, match="nejméně dvě"):
        await orchestration._normalize_action(
            cast(Any, FakeSession()),
            account_id,
            ToolCallDecision(
                name="memory_merge", arguments={"source_ids": [str(one.id)]}
            ),
            conversation,
            source_message,
        )
    with pytest.raises(NotFoundError):
        await orchestration._normalize_action(
            cast(Any, FakeSession(scalar_rows=[[one]])),
            account_id,
            ToolCallDecision(
                name="memory_merge",
                arguments={
                    "source_ids": [str(one.id), str(two.id)],
                    "content": "Spojené",
                },
            ),
            conversation,
            source_message,
        )
    merged, merge_preview, _ = await orchestration._normalize_action(
        cast(Any, FakeSession(scalar_rows=[[one, two]])),
        account_id,
        ToolCallDecision(
            name="memory_merge",
            arguments={
                "source_ids": [str(one.id), str(two.id)],
                "content": "Spojené",
                "category": "note",
            },
        ),
        conversation,
        source_message,
    )
    assert len(merged["source_versions"]) == 2
    assert merge_preview["result"] == "Spojené"

    target = SimpleNamespace(id=uuid4(), version=4, title=None, state="closed")
    orchestration.history.detail.return_value = (target, [])
    (
        history_args,
        history_preview,
        history_version,
    ) = await orchestration._normalize_action(
        cast(Any, FakeSession()),
        account_id,
        ToolCallDecision(
            name="history_restore", arguments={"conversation_id": str(target.id)}
        ),
        conversation,
        source_message,
    )
    assert history_args["expected_version"] == 4
    assert history_preview["target"] == str(target.id)
    assert history_version == 4
    with pytest.raises(ConflictError):
        await orchestration._normalize_action(
            cast(Any, FakeSession()),
            account_id,
            ToolCallDecision(
                name="history_delete",
                arguments={"conversation_id": str(target.id), "expected_version": 3},
            ),
            conversation,
            source_message,
        )
    with pytest.raises(DomainError, match="není pro tento run"):
        await orchestration._normalize_action(
            cast(Any, FakeSession()),
            account_id,
            ToolCallDecision(name="none"),
            conversation,
            source_message,
        )


@pytest.mark.asyncio
async def test_state_action_execution_and_integrity_for_every_supported_action() -> (
    None
):
    orchestration = service()
    account_id = uuid4()
    context = AuditContext("administrator", account_id)
    memory_id, conversation_id = uuid4(), uuid4()
    memory_row = SimpleNamespace(
        id=memory_id, state="active", version=2, purge_after=None
    )
    conversation_row = SimpleNamespace(
        id=conversation_id, state="closed", version=3, purge_after=None
    )
    orchestration.memory.create.return_value = memory_row
    orchestration.memory.update.return_value = memory_row
    orchestration.memory.soft_delete.return_value = memory_row
    orchestration.memory.restore.return_value = memory_row
    orchestration.memory.merge.return_value = memory_row
    orchestration.history.continue_from.return_value = conversation_row
    orchestration.history.soft_delete.return_value = conversation_row
    orchestration.history.restore.return_value = conversation_row

    async def execute(
        name: str, arguments: dict[str, Any], session: FakeSession | None = None
    ):
        action = ToolAction(
            id=uuid4(),
            run_id=uuid4(),
            name=name,
            arguments=arguments,
            arguments_hash=digest(arguments),
            side_effect="state_change",
            confirmation_required=True,
            state="running",
            preview={},
            idempotency_key=f"action-{name}-000000000000000000",
        )
        return await orchestration._execute_state_action(
            cast(Any, session or FakeSession()), account_id, action, context
        )

    created = await execute(
        "memory_create",
        {
            "content": "Paměť",
            "category": "note",
            "origin_type": "explicit_command",
            "confirmed": True,
        },
    )
    assert created["memory_id"] == str(memory_id)
    base_memory_args = {"memory_id": str(memory_id), "expected_version": 1}
    assert (await execute("memory_update", {**base_memory_args, "content": "Nová"}))[
        "version"
    ] == 2
    assert (await execute("memory_mark_outdated", base_memory_args))[
        "state"
    ] == "active"
    assert (
        await execute(
            "memory_delete", base_memory_args, FakeSession(scalar_values=[None])
        )
    )["recoverable_until"] is None
    assert (await execute("memory_restore", base_memory_args))["memory_id"] == str(
        memory_id
    )

    one, two = uuid4(), uuid4()
    orchestration.memory.get.side_effect = [
        SimpleNamespace(version=1),
        SimpleNamespace(version=2),
    ]
    merge_args = {
        "source_ids": [str(one), str(two)],
        "source_versions": {str(one): 1, str(two): 2},
        "target": {
            "content": "Spojená",
            "category": "note",
            "origin_type": "explicit_command",
            "confirmed": True,
        },
    }
    assert (await execute("memory_merge", merge_args))["memory_id"] == str(memory_id)
    orchestration.memory.get.side_effect = [SimpleNamespace(version=99)]
    with pytest.raises(ConflictError):
        await execute("memory_merge", merge_args)

    history_args = {"conversation_id": str(conversation_id), "expected_version": 2}
    assert (await execute("history_continue", history_args))["state"] == "closed"
    assert (
        await execute("history_delete", history_args, FakeSession(scalar_values=[None]))
    )["recoverable_until"] is None
    assert (await execute("history_restore", history_args))["version"] == 3
    with pytest.raises(DomainError, match="není podporován"):
        await execute("none", {})

    broken = ToolAction(
        id=uuid4(),
        run_id=uuid4(),
        name="memory_create",
        arguments={"content": "Změněno"},
        arguments_hash="0" * 64,
        side_effect="state_change",
        confirmation_required=True,
        state="running",
        preview={},
        idempotency_key="broken-action-000000000000000000",
    )
    with pytest.raises(DomainError, match="Integrita"):
        await orchestration._execute_state_action(
            cast(Any, FakeSession()), account_id, broken, context
        )


@pytest.mark.asyncio
async def test_primary_model_validation_and_helpers() -> None:
    orchestration = service()
    with pytest.raises(CapabilityUnavailableError):
        await orchestration._primary_model(cast(Any, FakeSession(scalar_values=[None])))
    with pytest.raises(CapabilityUnavailableError):
        await orchestration._primary_model(
            cast(
                Any,
                FakeSession(scalar_values=[SimpleNamespace(value={"value": "bad"})]),
            )
        )
    model_id, provider_id = uuid4(), uuid4()
    setting = SimpleNamespace(value={"value": str(model_id)})
    with pytest.raises(CapabilityUnavailableError):
        await orchestration._primary_model(
            cast(Any, FakeSession(scalar_values=[setting], get_values=[None]))
        )
    unsupported = SimpleNamespace(
        available=True, capabilities={"audio": True}, provider_id=provider_id
    )
    with pytest.raises(CapabilityUnavailableError):
        await orchestration._primary_model(
            cast(Any, FakeSession(scalar_values=[setting], get_values=[unsupported]))
        )
    model = SimpleNamespace(
        available=True, capabilities={"chat": True}, provider_id=provider_id
    )
    with pytest.raises(CapabilityUnavailableError):
        await orchestration._primary_model(
            cast(Any, FakeSession(scalar_values=[setting], get_values=[model, None]))
        )
    provider = SimpleNamespace(enabled=True, verification_state="verified")
    assert await orchestration._primary_model(
        cast(Any, FakeSession(scalar_values=[setting], get_values=[model, provider]))
    ) == (provider, model)

    first = ConversationMessage(content="12345")
    second = ConversationMessage(content="67890")
    assert orchestration._normalize("  žluťoučký   kůň ") == "žluťoučký kůň"
    assert orchestration._context_messages([first, second], 6) == [second]
    orchestration._validate_sources(decision(), set())
    invalid = decision(
        sources=[{"source_type": "memory", "source_id": str(uuid4()), "label": "Zdroj"}]
    )
    with pytest.raises(DomainError, match="nebyl součástí"):
        orchestration._validate_sources(invalid, set())
    usage = orchestration._usage(ChatResult("id", "", {}, None, 4))
    assert usage == {"input_units": 0, "output_units": 4}
    assert orchestration._merge_usage(usage, {"input_units": 3, "output_units": 2}) == {
        "input_units": 3,
        "output_units": 6,
    }
    assert "retenční" in orchestration._impact("memory_delete")
    assert "kanonických" in orchestration._impact("unknown")
    assert (
        await orchestration._setting(
            cast(
                Any, FakeSession(scalar_values=[SimpleNamespace(value={"value": 17})])
            ),
            "memory",
            "soft_delete_days",
            30,
        )
        == 17
    )
    assert (
        await orchestration._setting(
            cast(Any, FakeSession(scalar_values=[None])),
            "memory",
            "soft_delete_days",
            30,
        )
        == 30
    )
