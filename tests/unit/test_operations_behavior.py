from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from kajovodagmar.api.dependencies import RequestIdentity
from kajovodagmar.api.operations import BackupActionRequest, enqueue_backup_action
from kajovodagmar.audit.service import AuditContext
from kajovodagmar.errors import ConflictError, NotFoundError


class Session:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    async def get(self, *_args: Any, **_kwargs: Any) -> Any:
        return self.values.pop(0)


def identity() -> RequestIdentity:
    account_id = uuid4()
    account = cast(Any, SimpleNamespace(id=account_id))
    session = cast(Any, SimpleNamespace(id=uuid4()))
    return RequestIdentity(
        account,
        session,
        AuditContext(
            "administrator",
            actor_id=account_id,
            session_id=session.id,
            correlation_id="operations-unit",
        ),
    )


def request() -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                jobs=SimpleNamespace(enqueue=AsyncMock()),
                audit=SimpleNamespace(append=AsyncMock()),
            )
        )
    )


def payload(key: str = "operations-unit-key") -> BackupActionRequest:
    return BackupActionRequest(expected_version=3, idempotency_key=key)


@pytest.mark.asyncio
async def test_backup_action_idempotently_returns_existing_record() -> None:
    row = SimpleNamespace(id=uuid4())
    previous = SimpleNamespace(id=uuid4())
    result = await enqueue_backup_action(
        kind="backup_verify",
        operation="verify",
        backup_id=row.id,
        payload=payload(),
        request=request(),
        session=cast(Any, Session([previous, row])),
        identity=identity(),
    )
    assert result is row


@pytest.mark.asyncio
async def test_backup_action_rejects_missing_stale_and_incomplete_records() -> None:
    with pytest.raises(NotFoundError):
        await enqueue_backup_action(
            kind="backup_verify",
            operation="verify",
            backup_id=uuid4(),
            payload=payload("operations-unit-missing"),
            request=request(),
            session=cast(Any, Session([None, None])),
            identity=identity(),
        )

    stale = SimpleNamespace(id=uuid4(), version=2, state="completed")
    with pytest.raises(ConflictError, match="změnila"):
        await enqueue_backup_action(
            kind="backup_verify",
            operation="verify",
            backup_id=stale.id,
            payload=payload("operations-unit-stale"),
            request=request(),
            session=cast(Any, Session([None, stale])),
            identity=identity(),
        )

    queued = SimpleNamespace(id=uuid4(), version=3, state="queued")
    with pytest.raises(ConflictError, match="dokončenou"):
        await enqueue_backup_action(
            kind="backup_verify",
            operation="verify",
            backup_id=queued.id,
            payload=payload("operations-unit-queued"),
            request=request(),
            session=cast(Any, Session([None, queued])),
            identity=identity(),
        )


@pytest.mark.asyncio
async def test_backup_action_enqueues_and_audits_completed_record() -> None:
    row = SimpleNamespace(id=uuid4(), version=3, state="completed")
    operation_request = request()
    result = await enqueue_backup_action(
        kind="backup_restore_test",
        operation="restore_test",
        backup_id=row.id,
        payload=payload("operations-unit-success"),
        request=operation_request,
        session=cast(Any, Session([None, row])),
        identity=identity(),
    )
    assert result is row
    operation_request.app.state.jobs.enqueue.assert_awaited_once()
    operation_request.app.state.audit.append.assert_awaited_once()
