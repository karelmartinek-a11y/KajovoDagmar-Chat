from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.db.models import SecurityToken
from kajovodagmar.errors import DomainError
from kajovodagmar.security.crypto import generate_token, token_digest
from kajovodagmar.types import utc_now


async def issue_ticket(session: AsyncSession, account_id: UUID) -> tuple[str, str]:
    await session.execute(
        update(SecurityToken)
        .where(
            SecurityToken.account_id == account_id,
            SecurityToken.purpose == "realtime_ticket",
            SecurityToken.used_at.is_(None),
            SecurityToken.invalidated_at.is_(None),
        )
        .values(invalidated_at=utc_now())
    )
    token = generate_token(24)
    expires = utc_now() + timedelta(seconds=60)
    session.add(
        SecurityToken(
            account_id=account_id,
            purpose="realtime_ticket",
            token_digest=token_digest(token, "realtime_ticket"),
            expires_at=expires,
        )
    )
    return token, expires.isoformat()


async def consume_ticket(session: AsyncSession, token: str) -> UUID:
    row = await session.scalar(
        select(SecurityToken)
        .where(
            SecurityToken.token_digest == token_digest(token, "realtime_ticket"),
            SecurityToken.purpose == "realtime_ticket",
        )
        .with_for_update()
    )
    now = utc_now()
    if row is None or row.used_at or row.invalidated_at or row.expires_at <= now:
        raise DomainError("realtime_ticket_invalid", "Realtime vstupenka není platná.", 401)
    row.used_at = now
    return row.account_id
