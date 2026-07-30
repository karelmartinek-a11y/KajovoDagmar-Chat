from __future__ import annotations

import pytest

from kajovodagmar.audit.service import AuditContext, AuditService
from kajovodagmar.db.models import AdministratorAccount
from kajovodagmar.memory.schemas import MemoryCreate, MemoryUpdate
from kajovodagmar.memory.service import MemoryService

pytestmark = pytest.mark.integration


async def test_create_update_delete_restore(db_session) -> None:
    account = AdministratorAccount(username="Karmar78", state="active")
    db_session.add(account)
    await db_session.flush()
    service = MemoryService(AuditService())
    ctx = AuditContext("administrator", account.id)
    item = await service.create(
        db_session,
        account.id,
        MemoryCreate(
            content="Testovací preference",
            category="preference",
            origin_type="manual",
            confirmed=True,
        ),
        ctx,
    )
    assert item.state == "active"
    item = await service.update(
        db_session,
        account.id,
        item.id,
        MemoryUpdate(
            expected_version=item.version, content="Opravená testovací preference"
        ),
        ctx,
    )
    assert item.version == 2
    item = await service.soft_delete(
        db_session, account.id, item.id, item.version, 30, ctx
    )
    assert item.state == "deleted"
    item = await service.restore(db_session, account.id, item.id, item.version, ctx)
    assert item.state == "active"
