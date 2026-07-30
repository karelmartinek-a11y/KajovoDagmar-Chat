from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from kajovodagmar.audit.service import AuditContext
from kajovodagmar.conversations.schemas import (
    ConversationStart,
    TranscriptCorrection,
    UserTurn,
)
from kajovodagmar.conversations.service import ConversationService
from kajovodagmar.errors import ConflictError, DomainError, NotFoundError
from kajovodagmar.history.schemas import HistorySearch, MetadataUpdate
from kajovodagmar.history.service import HistoryService
from kajovodagmar.memory.schemas import MemoryCreate, MemorySearch, MemoryUpdate
from kajovodagmar.memory.service import MemoryService, contains_secret_instruction
from kajovodagmar.types import utc_now


class Rows:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def all(self) -> list[Any]:
        return self.values


class Session:
    def __init__(
        self,
        *,
        scalar_values: list[Any] | None = None,
        row_groups: list[list[Any]] | None = None,
    ) -> None:
        self.scalar_values = scalar_values or []
        self.row_groups = row_groups or []
        self.added: list[Any] = []

    async def scalar(self, _query: Any) -> Any:
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _query: Any) -> Rows:
        return Rows(self.row_groups.pop(0) if self.row_groups else [])

    def add(self, value: Any) -> None:
        self.added.append(value)
        if getattr(value, "id", None) is None:
            value.id = uuid4()
        if getattr(value, "version", None) is None:
            value.version = 1

    async def flush(self) -> None:
        return None

    async def refresh(self, _value: Any) -> None:
        return None


def audit() -> Any:
    return SimpleNamespace(append=AsyncMock())


def ctx(account_id: Any) -> AuditContext:
    return AuditContext("administrator", account_id)


def memory_item(**changes: Any) -> Any:
    item = SimpleNamespace(
        id=uuid4(),
        version=1,
        content="Původní fakt",
        category="note",
        state="active",
        event_at=None,
        valid_from=None,
        valid_until=None,
        keywords=[],
        confirmed_at=None,
        deleted_at=None,
        purge_after=None,
        merged_into_id=None,
    )
    for key, value in changes.items():
        setattr(item, key, value)
    return item


@pytest.mark.asyncio
async def test_memory_create_get_confirm_and_validation() -> None:
    service = MemoryService(cast(Any, audit()))
    account_id = uuid4()
    context = ctx(account_id)
    assert contains_secret_instruction("Ulož heslo abc")
    assert not contains_secret_instruction("Oblíbená barva je modrá")
    base: Any = {
        "category": "note",
        "origin_type": "manual",
    }
    with pytest.raises(DomainError, match="Tajné hodnoty"):
        await service.create(
            cast(Any, Session()),
            account_id,
            MemoryCreate(content="Moje api key je tajná", **base),
            context,
        )
    now = utc_now()
    with pytest.raises(DomainError, match="Konec platnosti"):
        await service.create(
            cast(Any, Session()),
            account_id,
            MemoryCreate(
                content="Časový fakt",
                valid_from=now,
                valid_until=now - timedelta(days=1),
                **base,
            ),
            context,
        )
    duplicate = memory_item()
    with pytest.raises(ConflictError, match="totožná"):
        await service.create(
            cast(Any, Session(scalar_values=[duplicate])),
            account_id,
            MemoryCreate(content="Původní fakt", **base),
            context,
        )
    session = Session(scalar_values=[None])
    created = await service.create(
        cast(Any, session),
        account_id,
        MemoryCreate(
            content="  Nový fakt  ",
            keywords=[" beta ", "alpha", "alpha", ""],
            **base,
        ),
        context,
    )
    assert created.content == "Nový fakt"
    assert created.keywords == ["alpha", "beta"]
    assert created.state == "active"
    assert len(session.added) == 4
    assert (
        await service.get(
            cast(Any, Session(scalar_values=[created])),
            account_id,
            created.id,
            include_deleted=True,
        )
        is created
    )
    with pytest.raises(NotFoundError):
        await service.get(cast(Any, Session()), account_id, uuid4())
    with pytest.raises(NotFoundError):
        await service.confirm(cast(Any, Session()), account_id, uuid4(), 1, context)
    with pytest.raises(ConflictError, match="mezitím"):
        await service.confirm(
            cast(Any, Session(scalar_values=[created])),
            account_id,
            created.id,
            99,
            context,
        )
    with pytest.raises(ConflictError, match="nečeká"):
        await service.confirm(
            cast(Any, Session(scalar_values=[created])),
            account_id,
            created.id,
            created.version,
            context,
        )
    pending = memory_item(state="pending_confirmation")
    confirmed = await service.confirm(
        cast(Any, Session(scalar_values=[pending])),
        account_id,
        pending.id,
        1,
        context,
    )
    assert confirmed.state == "active"
    assert confirmed.version == 2


@pytest.mark.asyncio
async def test_memory_update_delete_restore_merge_and_search() -> None:
    service: Any = MemoryService(cast(Any, audit()))
    account_id = uuid4()
    context = ctx(account_id)
    with pytest.raises(NotFoundError):
        await service.update(
            cast(Any, Session()),
            account_id,
            uuid4(),
            MemoryUpdate(expected_version=1, content="Nová hodnota"),
            context,
        )
    deleted = memory_item(state="deleted")
    with pytest.raises(ConflictError, match="nelze přímo"):
        await service.update(
            cast(Any, Session(scalar_values=[deleted])),
            account_id,
            deleted.id,
            MemoryUpdate(expected_version=1, content="Nová hodnota"),
            context,
        )
    active = memory_item()
    with pytest.raises(DomainError, match="Tajné hodnoty"):
        await service.update(
            cast(Any, Session(scalar_values=[active])),
            account_id,
            active.id,
            MemoryUpdate(expected_version=1, content="password xyz"),
            context,
        )
    now = utc_now()
    invalid = memory_item(valid_from=now)
    with pytest.raises(DomainError, match="Konec platnosti"):
        await service.update(
            cast(Any, Session(scalar_values=[invalid])),
            account_id,
            invalid.id,
            MemoryUpdate(
                expected_version=1,
                valid_until=now - timedelta(seconds=1),
            ),
            context,
        )
    updated = memory_item()
    result = await service.update(
        cast(Any, Session(scalar_values=[updated])),
        account_id,
        updated.id,
        MemoryUpdate(
            expected_version=1,
            content="  Aktualizováno ",
            category="preference",
            event_at=now,
            valid_from=now,
            valid_until=now + timedelta(days=1),
            mark_outdated=True,
        ),
        context,
    )
    assert result.content == "Aktualizováno"
    assert result.state == "outdated"
    assert result.version == 2

    with pytest.raises(NotFoundError):
        await service.soft_delete(
            cast(Any, Session()), account_id, uuid4(), 1, 30, context
        )
    already_deleted = memory_item(state="deleted")
    assert (
        await service.soft_delete(
            cast(Any, Session(scalar_values=[already_deleted])),
            account_id,
            already_deleted.id,
            1,
            30,
            context,
        )
        is already_deleted
    )
    to_delete = memory_item()
    deleted_result = await service.soft_delete(
        cast(Any, Session(scalar_values=[to_delete])),
        account_id,
        to_delete.id,
        1,
        30,
        context,
    )
    assert deleted_result.state == "deleted"
    with pytest.raises(NotFoundError):
        await service.restore(cast(Any, Session()), account_id, uuid4(), 1, context)
    unrestorable = memory_item(state="deleted", purge_after=None)
    with pytest.raises(ConflictError, match="nelze"):
        await service.restore(
            cast(Any, Session(scalar_values=[unrestorable])),
            account_id,
            unrestorable.id,
            1,
            context,
        )
    restorable = memory_item(
        state="deleted",
        deleted_at=now,
        purge_after=now + timedelta(days=1),
    )
    restored = await service.restore(
        cast(Any, Session(scalar_values=[restorable])),
        account_id,
        restorable.id,
        1,
        context,
    )
    assert restored.state == "active"

    with pytest.raises(DomainError, match="nejméně dvě"):
        await service.merge(
            cast(Any, Session()),
            account_id,
            [uuid4()],
            MemoryCreate(content="Spojené", category="note", origin_type="manual"),
            context,
        )
    one, two = memory_item(), memory_item(state="deleted")
    with pytest.raises(ConflictError, match="zdrojové"):
        await service.merge(
            cast(Any, Session(row_groups=[[one, two]])),
            account_id,
            [one.id, two.id],
            MemoryCreate(content="Spojené", category="note", origin_type="manual"),
            context,
        )
    one, two = memory_item(), memory_item(state="outdated")
    merged = memory_item(content="Spojené")
    service.create = AsyncMock(return_value=merged)
    merge_session = Session(row_groups=[[one, two]])
    result = await service.merge(
        cast(Any, merge_session),
        account_id,
        [one.id, two.id],
        MemoryCreate(content="Spojené", category="note", origin_type="manual"),
        context,
    )
    assert result is merged
    assert one.state == two.state == "merged"
    assert one.merged_into_id == merged.id

    ranges = MemorySearch(
        query="hledaný fakt",
        categories=["note"],
        from_at=now - timedelta(days=1),
        to_at=now + timedelta(days=1),
    )
    assert await service.search(
        cast(Any, Session(row_groups=[[merged]])),
        account_id,
        ranges,
        ranked_ids=[merged.id],
    ) == [merged]
    assert (
        await service.search(
            cast(Any, Session(row_groups=[[]])),
            account_id,
            MemorySearch(query="bez ranku"),
        )
        == []
    )
    assert await service.search(
        cast(Any, Session(row_groups=[[merged]])),
        account_id,
        MemorySearch(),
    ) == [merged]
    snapshot = service._snapshot(memory_item(event_at=now, keywords=["a"]))
    assert snapshot["event_at"] == now.isoformat()


def conversation(**changes: Any) -> Any:
    row = SimpleNamespace(
        id=uuid4(),
        account_id=uuid4(),
        state="active",
        language="cs",
        version=1,
        title=None,
        title_source="automatic",
        summary=None,
        summary_source="automatic",
        ended_at=None,
        deleted_at=None,
        purge_after=None,
        message_count=0,
        last_activity_at=utc_now(),
    )
    for key, value in changes.items():
        setattr(row, key, value)
    return row


@pytest.mark.asyncio
async def test_history_all_branches() -> None:
    service: Any = HistoryService(cast(Any, audit()))
    account_id = uuid4()
    context = ctx(account_id)
    now = utc_now()
    found = conversation(account_id=account_id)
    assert await service.search(
        cast(Any, Session(row_groups=[[found]])),
        account_id,
        HistorySearch(
            query="téma",
            from_at=now - timedelta(days=1),
            to_at=now + timedelta(days=1),
        ),
        ranked_ids=[found.id],
    ) == [found]
    assert (
        await service.search(
            cast(Any, Session(row_groups=[[]])), account_id, HistorySearch()
        )
        == []
    )
    with pytest.raises(NotFoundError):
        await service.detail(cast(Any, Session()), account_id, uuid4())
    message = SimpleNamespace(id=uuid4())
    detailed = await service.detail(
        cast(Any, Session(scalar_values=[found], row_groups=[[message]])),
        account_id,
        found.id,
        include_deleted=True,
    )
    assert detailed == (found, [message])

    with pytest.raises(NotFoundError):
        await service.update_metadata(
            cast(Any, Session()),
            account_id,
            uuid4(),
            MetadataUpdate(expected_version=1, title="Téma"),
            context,
        )
    with pytest.raises(ConflictError):
        await service.update_metadata(
            cast(Any, Session(scalar_values=[found])),
            account_id,
            found.id,
            MetadataUpdate(expected_version=99, title="Téma"),
            context,
        )
    updated = await service.update_metadata(
        cast(Any, Session(scalar_values=[found])),
        account_id,
        found.id,
        MetadataUpdate(expected_version=1, title="  Téma ", summary="  Souhrn "),
        context,
    )
    assert updated.title == "Téma"
    assert updated.summary == "Souhrn"
    service.detail = AsyncMock(return_value=(found, []))
    continued_session = Session()
    continued = await service.continue_from(
        cast(Any, continued_session), account_id, found.id, context
    )
    assert continued.continuation_of_id == found.id
    assert len(continued_session.added) == 2

    with pytest.raises(NotFoundError):
        await service.soft_delete(
            cast(Any, Session()), account_id, uuid4(), 1, 30, context
        )
    with pytest.raises(ConflictError):
        await service.soft_delete(
            cast(Any, Session(scalar_values=[found])),
            account_id,
            found.id,
            99,
            30,
            context,
        )
    found.version = 2
    deleted = await service.soft_delete(
        cast(Any, Session(scalar_values=[found])),
        account_id,
        found.id,
        2,
        30,
        context,
    )
    assert deleted.state == "deleted"
    with pytest.raises(NotFoundError):
        await service.restore(cast(Any, Session()), account_id, uuid4(), 1, context)
    with pytest.raises(ConflictError):
        await service.restore(
            cast(Any, Session(scalar_values=[deleted])),
            account_id,
            deleted.id,
            99,
            context,
        )
    deleted.purge_after = None
    with pytest.raises(ConflictError, match="nelze"):
        await service.restore(
            cast(Any, Session(scalar_values=[deleted])),
            account_id,
            deleted.id,
            deleted.version,
            context,
        )
    deleted.deleted_at = now
    deleted.purge_after = now + timedelta(days=1)
    deleted.ended_at = now
    restored = await service.restore(
        cast(Any, Session(scalar_values=[deleted])),
        account_id,
        deleted.id,
        deleted.version,
        context,
    )
    assert restored.state == "completed"


@pytest.mark.asyncio
async def test_conversation_all_branches() -> None:
    service = ConversationService(cast(Any, audit()))
    account_id = uuid4()
    context = ctx(account_id)
    original_id = uuid4()
    with pytest.raises(NotFoundError):
        await service.start(
            cast(Any, Session(scalar_values=[None])),
            account_id,
            ConversationStart(input_mode="text", continuation_of_id=original_id),
            context,
        )
    start_session = Session(scalar_values=[conversation(id=original_id)])
    started = await service.start(
        cast(Any, start_session),
        account_id,
        ConversationStart(input_mode="text", continuation_of_id=original_id),
        context,
    )
    assert started.continuation_of_id == original_id
    assert len(start_session.added) == 2

    with pytest.raises(NotFoundError):
        await service.add_user_turn(
            cast(Any, Session()),
            account_id,
            uuid4(),
            UserTurn(
                idempotency_key="conversation-user-0001",
                content="Text",
                input_mode="text",
            ),
            context,
        )
    closed = conversation(state="completed")
    with pytest.raises(ConflictError, match="uzavřené"):
        await service.add_user_turn(
            cast(Any, Session(scalar_values=[closed])),
            account_id,
            closed.id,
            UserTurn(
                idempotency_key="conversation-user-0002",
                content="Text",
                input_mode="text",
            ),
            context,
        )
    active = conversation(account_id=account_id)
    existing = SimpleNamespace(id=uuid4())
    assert (
        await service.add_user_turn(
            cast(Any, Session(scalar_values=[active, existing])),
            account_id,
            active.id,
            UserTurn(
                idempotency_key="conversation-user-0003",
                content="Text",
                input_mode="text",
            ),
            context,
        )
        is existing
    )
    user_session = Session(scalar_values=[active, None, 0])
    user_message = await service.add_user_turn(
        cast(Any, user_session),
        account_id,
        active.id,
        UserTurn(
            idempotency_key="conversation-user-0004",
            content="  Text  ",
            input_mode="text",
        ),
        context,
    )
    assert user_message.content == "Text"
    with pytest.raises(NotFoundError):
        await service.add_assistant_turn(
            cast(Any, Session()), uuid4(), "Odpověď", "assistant-key-0001", uuid4()
        )
    assert (
        await service.add_assistant_turn(
            cast(Any, Session(scalar_values=[active, existing])),
            active.id,
            "Odpověď",
            "assistant-key-0002",
            uuid4(),
        )
        is existing
    )
    assistant = await service.add_assistant_turn(
        cast(Any, Session(scalar_values=[active, None, 1])),
        active.id,
        "Odpověď",
        "assistant-key-0003",
        uuid4(),
        interrupted=True,
    )
    assert assistant.status == "interrupted"
    with pytest.raises(NotFoundError):
        await service.correct_transcript(
            cast(Any, Session()),
            account_id,
            uuid4(),
            TranscriptCorrection(
                expected_message_version=1, corrected_content="Oprava"
            ),
            context,
        )
    user_message.version = 1
    with pytest.raises(ConflictError):
        await service.correct_transcript(
            cast(Any, Session(scalar_values=[user_message])),
            account_id,
            user_message.id,
            TranscriptCorrection(
                expected_message_version=2, corrected_content="Oprava"
            ),
            context,
        )
    corrected_session = Session(scalar_values=[user_message])
    corrected = await service.correct_transcript(
        cast(Any, corrected_session),
        account_id,
        user_message.id,
        TranscriptCorrection(
            expected_message_version=1,
            corrected_content="  Oprava  ",
            request_new_answer=True,
        ),
        context,
    )
    assert corrected.content == "Oprava"
    assert len(corrected_session.added) == 2
    with pytest.raises(NotFoundError):
        await service.end(
            cast(Any, Session()), account_id, uuid4(), "user_ended", context
        )
    ended = await service.end(
        cast(Any, Session(scalar_values=[active])),
        account_id,
        active.id,
        "connection_lost",
        context,
    )
    assert ended.state == "interrupted"
    assert (
        await service.end(
            cast(Any, Session(scalar_values=[ended])),
            account_id,
            ended.id,
            "user_ended",
            context,
        )
        is ended
    )
