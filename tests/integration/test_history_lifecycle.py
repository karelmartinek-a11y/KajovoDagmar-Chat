from __future__ import annotations

import pytest

from kajovodagmar.audit.service import AuditContext, AuditService
from kajovodagmar.conversations.schemas import ConversationStart, UserTurn
from kajovodagmar.conversations.service import ConversationService
from kajovodagmar.db.models import AdministratorAccount
from kajovodagmar.history.schemas import HistorySearch
from kajovodagmar.history.service import HistoryService

pytestmark = pytest.mark.integration


async def test_closed_conversation_is_globally_searchable(db_session) -> None:
    account = AdministratorAccount(username="Karmar78", state="active")
    db_session.add(account)
    await db_session.flush()
    audit = AuditService()
    ctx = AuditContext("administrator", account.id)
    conversations = ConversationService(audit)
    row = await conversations.start(
        db_session, account.id, ConversationStart(input_mode="text", language="cs"), ctx
    )
    await conversations.add_user_turn(
        db_session,
        account.id,
        row.id,
        UserTurn(
            idempotency_key="0123456789abcdef",
            content="Hledaný syntetický obsah",
            input_mode="text",
            language="cs",
        ),
        ctx,
    )
    await conversations.end(db_session, account.id, row.id, "user_ended", ctx)
    results = await HistoryService(audit).search(
        db_session, account.id, HistorySearch(query="syntetický")
    )
    assert [item.id for item in results] == [row.id]
