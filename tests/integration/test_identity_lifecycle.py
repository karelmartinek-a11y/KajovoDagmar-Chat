from __future__ import annotations

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from kajovodagmar.audit.service import AuditContext, AuditService
from kajovodagmar.db.models import SystemInstance
from kajovodagmar.identity.schemas import InitializeRequest
from kajovodagmar.identity.service import IdentityService
from kajovodagmar.security.crypto import token_digest

pytestmark = pytest.mark.integration


async def test_initialization_is_single_use(db_session) -> None:
    secret = "synthetic-initialization-secret"
    instance = await db_session.scalar(
        select(SystemInstance)
        .where(SystemInstance.singleton_key == "primary")
        .with_for_update()
    )
    assert instance is not None
    instance.state = "uninitialized"
    instance.initialization_secret_digest = token_digest(secret, "initialization")
    instance.initialization_secret_consumed_at = None
    await db_session.flush()
    service = IdentityService(AuditService())
    request = InitializeRequest(
        username="Karmar78",
        initialization_secret=SecretStr(secret),
        password=SecretStr("bezpečná dlouhá přístupová věta"),
        password_confirmation=SecretStr("bezpečná dlouhá přístupová věta"),
        display_name="Testovací správce",
    )
    account = await service.initialize(db_session, request, AuditContext("test"))
    assert account.username == "Karmar78"
    instance = await db_session.scalar(
        select(SystemInstance).where(SystemInstance.singleton_key == "primary")
    )
    assert instance.state == "active"
    assert instance.initialization_secret_consumed_at is not None
