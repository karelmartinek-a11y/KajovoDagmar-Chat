from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from kajovodagmar.audit.service import AuditContext
from kajovodagmar.db.models import ExportRecord
from kajovodagmar.errors import ConflictError, NotFoundError
from kajovodagmar.files.service import ExportService


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

    async def flush(self) -> None:
        return None


def export_service(root: Path) -> Any:
    return ExportService(
        cast(Any, SimpleNamespace(append=AsyncMock())),
        cast(Any, SimpleNamespace(enqueue=AsyncMock())),
        root,
    )


@pytest.mark.asyncio
async def test_export_request_list_and_get_validation(tmp_path: Path) -> None:
    service = export_service(tmp_path)
    account_id = uuid4()
    context = AuditContext("administrator", account_id, correlation_id="export-request")
    with pytest.raises(ConflictError, match="druh exportu"):
        await service.request(
            cast(Any, Session()),
            account_id,
            kind="unknown",
            format="json",
            scope={},
            context=context,
        )
    with pytest.raises(ConflictError, match="JSON"):
        await service.request(
            cast(Any, Session()),
            account_id,
            kind="history",
            format="csv",
            scope={},
            context=context,
        )
    session = Session()
    record = await service.request(
        cast(Any, session),
        account_id,
        kind="history",
        format="json",
        scope={"all": True},
        context=context,
    )
    assert record.state == "queued"
    service.jobs.enqueue.assert_awaited_once()
    service.audit.append.assert_awaited_once()
    assert await service.list(
        cast(Any, Session(row_groups=[[record]])), account_id
    ) == [record]
    assert (
        await service.get(
            cast(Any, Session(scalar_values=[record])), account_id, record.id
        )
        is record
    )
    with pytest.raises(NotFoundError):
        await service.get(cast(Any, Session()), account_id, uuid4())


def record(root: Path, *, kind: str, format: str = "json") -> ExportRecord:
    return ExportRecord(
        id=uuid4(),
        account_id=uuid4(),
        kind=kind,
        state="queued",
        format=format,
        scope={},
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        version=1,
    )


@pytest.mark.asyncio
async def test_generate_json_markdown_and_expiration(tmp_path: Path) -> None:
    service = export_service(tmp_path)
    completed = record(tmp_path, kind="configuration")
    await service.generate(cast(Any, Session(scalar_values=[None])), uuid4())
    already = record(tmp_path, kind="configuration")
    already.state = "completed"
    await service.generate(cast(Any, Session(scalar_values=[already])), already.id)
    expired = record(tmp_path, kind="configuration")
    expired.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await service.generate(cast(Any, Session(scalar_values=[expired])), expired.id)
    assert expired.state == "expired"

    setting = SimpleNamespace(
        area="conversation",
        key="verbosity",
        value={"value": "balanced"},
        schema_version="1",
        version=2,
    )
    hidden = SimpleNamespace(
        area="security",
        key="provider_password",
        value={"value": "secret"},
        schema_version="1",
        version=1,
    )
    session = Session(scalar_values=[completed], row_groups=[[setting, hidden]])
    await service.generate(cast(Any, session), completed.id)
    assert completed.file_path is not None
    target = Path(completed.file_path)
    assert target.is_file()
    assert '"verbosity"' in target.read_text()
    assert "provider_password" not in target.read_text()
    assert completed.file_digest is not None
    assert completed.state == "completed"
    assert target.stat().st_mode & 0o777 == 0o600

    markdown = record(tmp_path, kind="configuration", format="markdown")
    await service.generate(
        cast(Any, Session(scalar_values=[markdown], row_groups=[[setting]])),
        markdown.id,
    )
    assert markdown.file_path is not None
    markdown_text = Path(markdown.file_path).read_text()
    assert "# Export KájovoDagmar" in markdown_text
    assert "## verbosity" in markdown_text


@pytest.mark.asyncio
async def test_payload_history_memory_and_purge(tmp_path: Path) -> None:
    service = export_service(tmp_path)
    now = datetime.now(timezone.utc)
    history_record = record(tmp_path, kind="history")
    conversation = SimpleNamespace(
        id=uuid4(),
        state="closed",
        title="Téma",
        summary="Souhrn",
        summary_source="automatic",
        started_at=now,
        ended_at=now,
        continuation_of_id=uuid4(),
        version=2,
    )
    message = SimpleNamespace(
        id=uuid4(),
        sequence=1,
        role="user",
        content="Dobrý den",
        status="final",
        interrupted=False,
        created_at=now,
        version=1,
    )
    history = await service._payload(
        cast(Any, Session(row_groups=[[conversation], [message]])), history_record
    )
    assert history["items"][0]["messages"][0]["content"] == "Dobrý den"

    memory_record = record(tmp_path, kind="memory")
    memory = SimpleNamespace(
        id=uuid4(),
        content="Fakt",
        category="note",
        state="active",
        origin_type="explicit_command",
        event_at=None,
        valid_from=None,
        valid_until=None,
        created_at=now,
        updated_at=now,
        version=2,
    )
    version = SimpleNamespace(
        version_number=1,
        content="Fakt",
        category="note",
        state="active",
        changed_at=now,
    )
    source = SimpleNamespace(
        source_type="conversation",
        conversation_id=conversation.id,
        message_id=message.id,
        source_excerpt="Dobrý den",
    )
    memory_payload = await service._payload(
        cast(Any, Session(row_groups=[[memory], [version], [source]])), memory_record
    )
    assert memory_payload["items"][0]["sources"][0]["quoted_text"] == "Dobrý den"

    safe_file = tmp_path / str(memory_record.account_id) / "expired.json"
    safe_file.parent.mkdir()
    safe_file.write_text("{}")
    expired_with_file = record(tmp_path, kind="memory")
    expired_with_file.file_path = str(safe_file)
    unsafe = record(tmp_path, kind="history")
    unsafe.file_path = "/tmp/not-owned-export.json"
    removed = await service.purge_expired(
        cast(Any, Session(row_groups=[[expired_with_file, unsafe]]))
    )
    assert removed == 1
    assert not safe_file.exists()
    assert expired_with_file.state == "expired"
    assert unsafe.file_path is None
