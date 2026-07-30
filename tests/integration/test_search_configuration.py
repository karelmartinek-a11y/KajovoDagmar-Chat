from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_czech_search_configuration_indexes_text(
    db_session: AsyncSession,
) -> None:
    vector = await db_session.scalar(
        text("SELECT to_tsvector('czech'::regconfig, 'Kájovo ověřené hledání')::text")
    )

    assert vector
    assert "ověřené" in vector
