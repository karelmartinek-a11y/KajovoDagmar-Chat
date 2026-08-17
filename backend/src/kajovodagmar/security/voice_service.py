from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.audit.service import AuditContext, AuditService
from kajovodagmar.db.models import (
    AdministratorAccount,
    ServiceAccessNotice,
    VoiceServiceApiKey,
)
from kajovodagmar.errors import UnauthorizedError
from kajovodagmar.security.crypto import secure_equals, token_digest
from kajovodagmar.types import utc_now

SCOPE = "voice.realtime.test"


@dataclass(frozen=True, slots=True)
class VoiceServiceIdentity:
    key: VoiceServiceApiKey
    audit_context: AuditContext


def read_key(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return None
    return value or None


async def sync_key_metadata(session: AsyncSession, path: Path) -> None:
    value = read_key(path)
    if not value:
        await session.execute(
            update(VoiceServiceApiKey)
            .where(
                VoiceServiceApiKey.scope == SCOPE,
                VoiceServiceApiKey.revoked_at.is_(None),
            )
            .values(revoked_at=utc_now(), revoke_reason="secret_file_missing")
        )
        return
    digest = token_digest(value, "voice_service_api")
    await session.execute(
        update(VoiceServiceApiKey)
        .where(
            VoiceServiceApiKey.scope == SCOPE,
            VoiceServiceApiKey.secret_digest != digest,
            VoiceServiceApiKey.revoked_at.is_(None),
        )
        .values(revoked_at=utc_now(), revoke_reason="rotated")
    )
    row = await session.scalar(
        select(VoiceServiceApiKey).where(VoiceServiceApiKey.secret_digest == digest)
    )
    if row is None:
        session.add(
            VoiceServiceApiKey(
                key_prefix=value[:12],
                secret_digest=digest,
                scope=SCOPE,
            )
        )


async def authenticate(
    session: AsyncSession,
    presented: str | None,
    *,
    key_file: Path,
    network_context: str,
    correlation_id: str | None,
    audit: AuditService,
) -> VoiceServiceIdentity:
    if not presented:
        raise UnauthorizedError("Servisní hlasový přístup nebyl předán.")
    current_value = read_key(key_file)
    if not current_value or not secure_equals(current_value, presented):
        raise UnauthorizedError("Servisní hlasový přístup není platný.")
    digest = token_digest(presented, "voice_service_api")
    row = await session.scalar(
        select(VoiceServiceApiKey).where(
            VoiceServiceApiKey.secret_digest == digest,
            VoiceServiceApiKey.scope == SCOPE,
            VoiceServiceApiKey.revoked_at.is_(None),
        )
    )
    if row is None or not secure_equals(row.secret_digest, digest):
        await audit.append(
            session,
            context=AuditContext(
                "voice_service", network_context=network_context, correlation_id=correlation_id
            ),
            event_type="voice_service.access_denied",
            result="denied",
            details={"scope": SCOPE},
        )
        raise UnauthorizedError("Servisní hlasový přístup není platný.")
    now = utc_now()
    row.last_used_at = now
    primary = await session.scalar(
        select(AdministratorAccount).where(AdministratorAccount.username == "Karmar78")
    )
    if primary is not None:
        session.add(
            ServiceAccessNotice(
                account_id=primary.id,
                api_key_id=row.id,
                occurred_at=now,
                result="accepted",
                endpoint="realtime.ticket",
                network_context=network_context,
                correlation_id=correlation_id,
            )
        )
    await audit.append(
        session,
        context=AuditContext(
            "voice_service", row.id, network_context=network_context, correlation_id=correlation_id
        ),
        event_type="voice_service.access",
        result="success",
        target_type="voice_service_api_key",
        target_id=row.id,
        details={"scope": SCOPE, "key_prefix": row.key_prefix, "endpoint": "realtime.ticket"},
    )
    return VoiceServiceIdentity(
        row,
        AuditContext(
            "voice_service", row.id, network_context=network_context, correlation_id=correlation_id
        ),
    )


async def acknowledge_notice(session: AsyncSession, account_id: UUID, notice_id: UUID) -> None:
    row = await session.scalar(
        select(ServiceAccessNotice).where(
            ServiceAccessNotice.id == notice_id,
            ServiceAccessNotice.account_id == account_id,
            ServiceAccessNotice.acknowledged_at.is_(None),
        )
    )
    if row is not None:
        row.acknowledged_at = utc_now()
