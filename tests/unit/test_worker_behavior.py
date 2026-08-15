from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from kajovodagmar.errors import CapabilityUnavailableError
from kajovodagmar.worker import Worker


class ScalarRows:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows


class FakeSession:
    def __init__(
        self,
        *,
        gets: list[Any] | None = None,
        scalars: list[list[Any]] | None = None,
        scalar_values: list[Any] | None = None,
    ) -> None:
        self.gets = list(gets or [])
        self.scalar_rows = list(scalars or [])
        self.scalar_values = list(scalar_values or [])
        self.added: list[Any] = []
        self.executed: list[Any] = []
        self.flush_count = 0

    async def get(self, *_args: Any, **_kwargs: Any) -> Any:
        return self.gets.pop(0)

    async def scalars(self, _query: Any) -> ScalarRows:
        return ScalarRows(self.scalar_rows.pop(0))

    async def scalar(self, _query: Any) -> Any:
        return self.scalar_values.pop(0)

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_count += 1

    async def execute(self, query: Any) -> None:
        self.executed.append(query)


def worker_shell() -> Any:
    worker = cast(Any, Worker.__new__(Worker))
    worker.jobs = SimpleNamespace(
        enqueue=AsyncMock(), claim=AsyncMock(), complete=AsyncMock(), fail=AsyncMock()
    )
    worker.providers = SimpleNamespace(runtime=AsyncMock())
    worker.notifications = SimpleNamespace(process_password_reset=AsyncMock())
    worker.exports = SimpleNamespace(generate=AsyncMock(), purge_expired=AsyncMock())
    worker.orchestration = SimpleNamespace(answer=AsyncMock())
    return worker


@pytest.mark.asyncio
async def test_dispatches_each_supported_outbox_event() -> None:
    worker = worker_shell()
    events = [
        SimpleNamespace(
            event_type="memory.index_requested",
            payload={"memory_id": str(uuid4())},
            published_at=None,
            attempts=0,
        ),
        SimpleNamespace(
            event_type="conversation.closed",
            payload={"conversation_id": str(uuid4())},
            published_at=None,
            attempts=0,
        ),
        SimpleNamespace(
            event_type="conversation.corrected_turn_reprocess_requested",
            payload={"message_id": str(uuid4())},
            published_at=None,
            attempts=0,
        ),
        SimpleNamespace(
            event_type="ignored", payload={}, published_at=None, attempts=0
        ),
    ]
    session = FakeSession(scalars=[events])

    assert await worker.dispatch_outbox(session) == 4
    assert worker.jobs.enqueue.await_count == 4
    assert all(
        event.published_at is not None and event.attempts == 1 for event in events
    )


@pytest.mark.asyncio
async def test_memory_index_creates_updates_and_embeds() -> None:
    worker = worker_shell()
    memory_id = uuid4()
    memory = SimpleNamespace(
        id=memory_id,
        account_id=uuid4(),
        content="Doložená preference",
        version=3,
    )
    no_embedding = FakeSession(
        gets=[memory],
        scalar_values=[None, None],
    )
    await worker.memory_index(
        no_embedding, SimpleNamespace(payload={"memory_id": str(memory_id)})
    )
    assert no_embedding.flush_count == 1
    assert no_embedding.added[0].searchable_text == memory.content

    document = SimpleNamespace(
        id=uuid4(),
        searchable_text="stará",
        source_version=1,
        stale=True,
        version=1,
    )
    setting = SimpleNamespace(value={"value": str(uuid4())})
    model = SimpleNamespace(external_id="embedding-model")
    provider = SimpleNamespace()
    runtime = SimpleNamespace(
        embed=AsyncMock(return_value=[[0.25, -0.5] + [0.0] * 1534])
    )
    worker.resolve_model = AsyncMock(return_value=(model, provider))
    worker.providers.runtime.return_value = runtime
    with_embedding = FakeSession(
        gets=[memory],
        scalar_values=[document, setting, None],
    )
    await worker.memory_index(
        with_embedding, SimpleNamespace(payload={"memory_id": str(memory_id)})
    )
    assert document.searchable_text == memory.content
    assert document.version == 2
    assert with_embedding.added[0].dimensions == 1536

    existing = SimpleNamespace(vector_data="", dimensions=0, version=1)
    runtime.embed.return_value = [[1.0] + [0.0] * 1535]
    update_embedding = FakeSession(
        gets=[memory],
        scalar_values=[document, setting, existing],
    )
    await worker.memory_index(
        update_embedding, SimpleNamespace(payload={"memory_id": str(memory_id)})
    )
    assert existing.vector_data.startswith("[1,0,0")
    assert existing.version == 2

    runtime.embed.return_value = []
    invalid_embedding = FakeSession(
        gets=[memory],
        scalar_values=[document, setting],
    )
    with pytest.raises(RuntimeError, match="přesně jednu"):
        await worker.memory_index(
            invalid_embedding, SimpleNamespace(payload={"memory_id": str(memory_id)})
        )

    missing = FakeSession(gets=[None])
    await worker.memory_index(
        missing, SimpleNamespace(payload={"memory_id": str(memory_id)})
    )
    assert not missing.added


@pytest.mark.asyncio
async def test_conversation_finalize_handles_empty_and_model_summary() -> None:
    worker = worker_shell()
    conversation_id = uuid4()
    missing = FakeSession(gets=[None])
    await worker.conversation_finalize(
        missing, SimpleNamespace(payload={"conversation_id": str(conversation_id)})
    )

    empty_conversation = SimpleNamespace(id=conversation_id)
    empty = FakeSession(gets=[empty_conversation], scalars=[[]])
    await worker.conversation_finalize(
        empty, SimpleNamespace(payload={"conversation_id": str(conversation_id)})
    )
    assert empty_conversation.title == "Prázdný rozhovor"

    unavailable = FakeSession(
        gets=[SimpleNamespace(id=conversation_id)],
        scalars=[[SimpleNamespace(role="user", content="Obsah")]],
        scalar_values=[None],
    )
    with pytest.raises(CapabilityUnavailableError):
        await worker.conversation_finalize(
            unavailable,
            SimpleNamespace(payload={"conversation_id": str(conversation_id)}),
        )

    conversation = SimpleNamespace(id=conversation_id, version=1)
    setting = SimpleNamespace(value={"value": str(uuid4())})
    model = SimpleNamespace(external_id="summary-model")
    provider = SimpleNamespace()
    runtime = SimpleNamespace(
        chat=AsyncMock(
            return_value=SimpleNamespace(
                structured={"title": "Pravdivý název", "summary": "Doložené shrnutí."}
            )
        )
    )
    worker.resolve_model = AsyncMock(return_value=(model, provider))
    worker.providers.runtime.return_value = runtime
    summarized = FakeSession(
        gets=[conversation],
        scalars=[
            [
                SimpleNamespace(role="user", content="Dotaz"),
                SimpleNamespace(role="assistant", content="Odpověď"),
            ]
        ],
        scalar_values=[setting],
    )
    await worker.conversation_finalize(
        summarized, SimpleNamespace(payload={"conversation_id": str(conversation_id)})
    )
    assert conversation.title == "Pravdivý název"
    assert conversation.summary == "Doložené shrnutí."
    assert conversation.version == 2
    assert summarized.added[0].source == "automatic"


@pytest.mark.asyncio
async def test_conversation_index_creates_and_updates_documents() -> None:
    worker = worker_shell()
    conversation_id = uuid4()
    job = SimpleNamespace(payload={"conversation_id": str(conversation_id)})
    await worker.conversation_index(FakeSession(gets=[None]), job)

    conversation = SimpleNamespace(
        id=conversation_id,
        account_id=uuid4(),
        title="Název",
        summary="Shrnutí",
        version=2,
    )
    message = SimpleNamespace(role="user", content="Doložený přepis")
    created = FakeSession(
        gets=[conversation],
        scalars=[[message]],
        scalar_values=[None, None],
    )
    await worker.conversation_index(created, job)
    assert created.added[0].searchable_text.startswith("Název")

    document = SimpleNamespace(
        id=uuid4(),
        searchable_text="",
        source_version=1,
        stale=True,
        version=1,
    )
    setting = SimpleNamespace(value={"value": str(uuid4())})
    model = SimpleNamespace(external_id="embed")
    provider = SimpleNamespace()
    runtime = SimpleNamespace(embed=AsyncMock(return_value=[[0.1, 0.2] + [0.0] * 1534]))
    worker.resolve_model = AsyncMock(return_value=(model, provider))
    worker.providers.runtime.return_value = runtime
    embedded = FakeSession(
        gets=[conversation],
        scalars=[[message]],
        scalar_values=[document, setting, None],
    )
    await worker.conversation_index(embedded, job)
    assert document.version == 2
    assert embedded.added[0].dimensions == 1536

    runtime.embed.return_value = []
    invalid = FakeSession(
        gets=[conversation],
        scalars=[[message]],
        scalar_values=[document, setting],
    )
    with pytest.raises(RuntimeError, match="přesně jednu"):
        await worker.conversation_index(invalid, job)


@pytest.mark.asyncio
async def test_worker_delegates_jobs_purge_and_reprocessing() -> None:
    worker = worker_shell()
    job = SimpleNamespace(
        payload={"message_id": str(uuid4()), "export_id": str(uuid4())},
        correlation_id="correlation",
    )
    await worker.corrected_turn_reprocess(FakeSession(gets=[None]), job)
    message = SimpleNamespace(id=uuid4(), conversation_id=uuid4())
    await worker.corrected_turn_reprocess(FakeSession(gets=[message, None]), job)
    conversation = SimpleNamespace(id=message.conversation_id, account_id=uuid4())
    await worker.corrected_turn_reprocess(
        FakeSession(gets=[message, conversation]), job
    )
    worker.orchestration.answer.assert_awaited_once()
    worker.jobs.enqueue.assert_awaited()

    await worker.password_reset_notification(FakeSession(), job)
    worker.notifications.process_password_reset.assert_awaited_once()
    await worker.export_generate(FakeSession(), job)
    worker.exports.generate.assert_awaited_once()
    purge_session = FakeSession()
    await worker.purge_expired(purge_session, job)
    assert len(purge_session.executed) == 2
    worker.exports.purge_expired.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_model_requires_available_verified_configuration() -> None:
    model_id = uuid4()
    with pytest.raises(CapabilityUnavailableError):
        await cast(Any, Worker.resolve_model)(FakeSession(gets=[None]), model_id)

    unavailable = SimpleNamespace(available=False)
    with pytest.raises(CapabilityUnavailableError):
        await cast(Any, Worker.resolve_model)(FakeSession(gets=[unavailable]), model_id)

    model = SimpleNamespace(available=True, provider_id=uuid4())
    with pytest.raises(CapabilityUnavailableError):
        await cast(Any, Worker.resolve_model)(FakeSession(gets=[model, None]), model_id)
    disabled = SimpleNamespace(enabled=False, verification_state="verified")
    with pytest.raises(CapabilityUnavailableError):
        await cast(Any, Worker.resolve_model)(
            FakeSession(gets=[model, disabled]), model_id
        )
    verified = SimpleNamespace(enabled=True, verification_state="verified")
    assert await cast(Any, Worker.resolve_model)(
        FakeSession(gets=[model, verified]), model_id
    ) == (
        model,
        verified,
    )
