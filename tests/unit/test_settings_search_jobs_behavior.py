from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from kajovodagmar.audit.service import AuditContext
from kajovodagmar.errors import (
    CapabilityUnavailableError,
    ConflictError,
    DomainError,
    NotFoundError,
)
from kajovodagmar.jobs.service import JobService
from kajovodagmar.search.service import HybridSearchService
from kajovodagmar.settings.service import SettingsService


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
        get_values: list[Any] | None = None,
        execute_rows: list[list[Any]] | None = None,
    ) -> None:
        self.scalar_values = scalar_values or []
        self.row_groups = row_groups or []
        self.get_values = get_values or []
        self.execute_rows = execute_rows or []
        self.added: list[Any] = []
        self.execute_parameters: list[Any] = []

    async def scalar(self, _query: Any) -> Any:
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _query: Any) -> Rows:
        return Rows(self.row_groups.pop(0) if self.row_groups else [])

    async def get(self, *_args: Any) -> Any:
        return self.get_values.pop(0) if self.get_values else None

    async def execute(self, _query: Any, parameters: Any = None) -> list[Any]:
        self.execute_parameters.append(parameters)
        return self.execute_rows.pop(0) if self.execute_rows else []

    def add(self, value: Any) -> None:
        self.added.append(value)
        if getattr(value, "id", None) is None:
            value.id = uuid4()
        if getattr(value, "version", None) is None:
            value.version = 1

    async def flush(self) -> None:
        return None


def settings_service() -> Any:
    return SettingsService(cast(Any, SimpleNamespace(append=AsyncMock())))


@pytest.mark.asyncio
async def test_settings_effective_update_history_and_restore() -> None:
    service = settings_service()
    stored = SimpleNamespace(
        area="conversation", key="verbosity", value={"value": "detailed"}, version=4
    )
    effective = await service.effective(cast(Any, Session(row_groups=[[stored]])))
    assert effective["conversation"]["verbosity"]["value"] == "detailed"
    assert effective["memory"]["soft_delete_days"]["version"] == 0
    account_id = uuid4()
    context = AuditContext("administrator", account_id)
    with pytest.raises(DomainError, match="není podporováno"):
        await service.update_area(
            cast(Any, Session()),
            "conversation",
            {"unknown": {"value": "x", "version": 0}},
            account_id,
            context,
        )
    with pytest.raises(ConflictError):
        await service.update_area(
            cast(Any, Session(scalar_values=[stored])),
            "conversation",
            {"verbosity": {"value": "short", "version": 3}},
            account_id,
            context,
        )
    create_session = Session(scalar_values=[None])
    created = await service.update_area(
        cast(Any, create_session),
        "conversation",
        {"verbosity": {"value": "short", "version": 0}},
        account_id,
        context,
    )
    assert created["verbosity"]["value"] == "short"
    row = create_session.added[0]
    update_session = Session(scalar_values=[row])
    updated = await service.update_area(
        cast(Any, update_session),
        "conversation",
        {"verbosity": {"value": "balanced", "version": 1}},
        account_id,
        context,
    )
    assert updated["verbosity"]["version"] == 2
    assert (
        await service.history(
            cast(Any, Session(scalar_values=[None])), "conversation", "verbosity"
        )
        == []
    )
    revision = SimpleNamespace(
        setting_id=row.id, revision_number=1, value={"value": "short"}
    )
    assert await service.history(
        cast(Any, Session(scalar_values=[row], row_groups=[[revision]])),
        "conversation",
        "verbosity",
    ) == [revision]

    with pytest.raises(DomainError):
        await service.restore_revision(
            cast(Any, Session()),
            "conversation",
            "unknown",
            1,
            1,
            account_id,
            context,
        )
    with pytest.raises(NotFoundError, match="historii"):
        await service.restore_revision(
            cast(Any, Session(scalar_values=[None])),
            "conversation",
            "verbosity",
            1,
            1,
            account_id,
            context,
        )
    with pytest.raises(ConflictError):
        await service.restore_revision(
            cast(Any, Session(scalar_values=[row])),
            "conversation",
            "verbosity",
            1,
            99,
            account_id,
            context,
        )
    with pytest.raises(NotFoundError, match="verze"):
        await service.restore_revision(
            cast(Any, Session(scalar_values=[row, None])),
            "conversation",
            "verbosity",
            1,
            row.version,
            account_id,
            context,
        )
    restored = await service.restore_revision(
        cast(Any, Session(scalar_values=[row, revision])),
        "conversation",
        "verbosity",
        1,
        row.version,
        account_id,
        context,
    )
    assert restored.value == {"value": "short"}


@pytest.mark.asyncio
async def test_model_selection_is_validated_and_embedding_change_marks_index_stale() -> (
    None
):
    service = SettingsService(
        cast(Any, SimpleNamespace(append=AsyncMock())),
        providers=SimpleNamespace(),
        jobs=None,
    )
    provider_id = uuid4()
    provider = SimpleNamespace(
        id=provider_id, enabled=True, verification_state="verified"
    )
    model_id = uuid4()
    embedding = SimpleNamespace(
        id=model_id,
        provider_id=provider_id,
        available=True,
        role="embedding_model",
    )
    context = AuditContext("administrator", uuid4())
    session = Session(
        scalar_values=[None, 3],
        get_values=[embedding, provider],
        execute_rows=[[]],
    )
    result = await service.update_area(
        cast(Any, session),
        "models",
        {"embedding_model": {"value": str(model_id), "version": 0}},
        uuid4(),
        context,
    )
    assert result["embedding_model"]["value"] == str(model_id)
    assert session.execute_parameters == [None]


@pytest.mark.asyncio
async def test_model_selection_rejects_invalid_identifier_and_wrong_role() -> None:
    service = SettingsService(
        cast(Any, SimpleNamespace(append=AsyncMock())), providers=SimpleNamespace()
    )
    context = AuditContext("administrator", uuid4())
    with pytest.raises(DomainError, match="není platný"):
        await service.update_area(
            cast(Any, Session()),
            "models",
            {"conversation_model": {"value": "not-a-uuid", "version": 0}},
            uuid4(),
            context,
        )
    model = SimpleNamespace(available=True, role="speech_model", provider_id=uuid4())
    with pytest.raises(DomainError, match="není dostupný"):
        await service.update_area(
            cast(Any, Session(get_values=[model])),
            "models",
            {"conversation_model": {"value": str(uuid4()), "version": 0}},
            uuid4(),
            context,
        )


@pytest.mark.asyncio
async def test_hybrid_search_text_semantic_and_embedding_guards() -> None:
    providers = SimpleNamespace(runtime=AsyncMock())
    search: Any = HybridSearchService(cast(Any, providers))
    assert (
        await search.ranked_owner_ids(
            cast(Any, Session()),
            account_id=uuid4(),
            owner_type="memory",
            query=" ",
            limit=5,
        )
        == []
    )
    owner = uuid4()
    search._query_embedding = AsyncMock(return_value=(None, None))
    text_session = Session(execute_rows=[[SimpleNamespace(owner_id=owner)]])
    assert await search.ranked_owner_ids(
        cast(Any, text_session),
        account_id=uuid4(),
        owner_type="memory",
        query="dotaz",
        limit=5,
    ) == [owner]
    search._query_embedding = AsyncMock(return_value=([0.1, 0.2], "embed-model"))
    semantic_session = Session(execute_rows=[[SimpleNamespace(owner_id=owner)]])
    assert await search.ranked_owner_ids(
        cast(Any, semantic_session),
        account_id=uuid4(),
        owner_type="conversation",
        query="dotaz",
        limit=3,
    ) == [owner]
    assert semantic_session.execute_parameters[0]["vector"] == "[0.1,0.2]"
    assert semantic_session.execute_parameters[0]["candidate_limit"] == 40

    real = HybridSearchService(cast(Any, providers))
    assert await real._query_embedding(
        cast(Any, Session(scalar_values=[None])), "q"
    ) == (None, None)
    invalid_setting = SimpleNamespace(value={"value": "invalid"})
    assert await real._query_embedding(
        cast(Any, Session(scalar_values=[invalid_setting])), "q"
    ) == (None, None)
    model_id = uuid4()
    setting = SimpleNamespace(value={"value": str(model_id)})
    unavailable = SimpleNamespace(available=False, capabilities={}, provider_id=uuid4())
    assert await real._query_embedding(
        cast(Any, Session(scalar_values=[setting], get_values=[unavailable])), "q"
    ) == (None, None)
    model = SimpleNamespace(
        available=True,
        capabilities={"embeddings": True},
        provider_id=uuid4(),
        external_id="embed-model",
    )
    disabled = SimpleNamespace(enabled=False, verification_state="verified")
    assert await real._query_embedding(
        cast(Any, Session(scalar_values=[setting], get_values=[model, disabled])), "q"
    ) == (None, None)
    provider = SimpleNamespace(enabled=True, verification_state="verified")
    providers.runtime.side_effect = CapabilityUnavailableError(
        "embedding", "Embedding není dostupný."
    )
    assert await real._query_embedding(
        cast(Any, Session(scalar_values=[setting], get_values=[model, provider])), "q"
    ) == (None, None)
    providers.runtime.side_effect = None
    providers.runtime.return_value = SimpleNamespace(embed=AsyncMock(return_value=[]))
    assert await real._query_embedding(
        cast(Any, Session(scalar_values=[setting], get_values=[model, provider])), "q"
    ) == (None, None)
    providers.runtime.return_value.embed.return_value = [[0.4, 0.5]]
    assert await real._query_embedding(
        cast(Any, Session(scalar_values=[setting], get_values=[model, provider])), "q"
    ) == ([0.4, 0.5], "embed-model")


@pytest.mark.asyncio
async def test_job_lifecycle_retry_and_terminal_failure() -> None:
    jobs = JobService()
    session = Session()
    created = await jobs.enqueue(
        cast(Any, session),
        "export_generate",
        {"id": "1"},
        priority=10,
        delay_seconds=5,
        correlation_id="job-test",
    )
    assert created.state == "queued"
    created.attempts = 0
    created.max_attempts = 2
    claimed = await jobs.claim(
        cast(Any, Session(row_groups=[[created]])), "worker-1", limit=1
    )
    assert claimed[0].state == "running"
    assert claimed[0].attempts == 1
    await jobs.fail(created, "temporary")
    assert created.state == "queued"
    assert created.last_error_code == "temporary"
    created.attempts = created.max_attempts
    await jobs.fail(created, "terminal")
    assert created.state == "failed"
    await jobs.complete(created)
    assert created.state == "completed"
    assert created.locked_by is None
