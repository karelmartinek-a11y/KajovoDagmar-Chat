from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.db.models import AuditEvent
from kajovodagmar.types import utc_now


@dataclass(frozen=True, slots=True)
class AuditContext:
    actor_type: str
    actor_id: UUID | None = None
    session_id: UUID | None = None
    network_context: str | None = None
    correlation_id: str | None = None


class AuditService:
    async def append(
        self,
        session: AsyncSession,
        *,
        context: AuditContext,
        event_type: str,
        result: str,
        target_type: str | None = None,
        target_id: UUID | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        previous = await session.scalar(select(AuditEvent).order_by(desc(AuditEvent.id)).limit(1))
        previous_hash = previous.event_hash if previous else None
        occurred_at = utc_now()
        safe_details = self._sanitize(details or {})
        canonical = json.dumps(
            {
                "occurred_at": occurred_at.isoformat(),
                "actor_type": context.actor_type,
                "actor_id": str(context.actor_id) if context.actor_id else None,
                "session_id": str(context.session_id) if context.session_id else None,
                "event_type": event_type,
                "target_type": target_type,
                "target_id": str(target_id) if target_id else None,
                "result": result,
                "network_context": context.network_context,
                "correlation_id": context.correlation_id,
                "details": safe_details,
                "previous_hash": previous_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        event = AuditEvent(
            occurred_at=occurred_at,
            actor_type=context.actor_type,
            actor_id=context.actor_id,
            session_id=context.session_id,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            result=result,
            network_context=context.network_context,
            correlation_id=context.correlation_id,
            details=safe_details,
            previous_hash=previous_hash,
            event_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        )
        session.add(event)
        await session.flush()
        return event

    @staticmethod
    def _sanitize(details: dict[str, Any]) -> dict[str, Any]:
        forbidden = {
            "password",
            "token",
            "secret",
            "api_key",
            "authorization",
            "content",
            "transcript",
        }
        result: dict[str, Any] = {}
        for key, value in details.items():
            if any(word in key.casefold() for word in forbidden):
                result[key] = "[redacted]"
            elif isinstance(value, str) and len(value) > 500:
                result[key] = value[:500]
            else:
                result[key] = value
        return result

    @staticmethod
    def verify_chain(events: list[AuditEvent]) -> tuple[bool, int | None]:
        previous_hash: str | None = None
        for event in events:
            canonical = json.dumps(
                {
                    "occurred_at": event.occurred_at.isoformat(),
                    "actor_type": event.actor_type,
                    "actor_id": str(event.actor_id) if event.actor_id else None,
                    "session_id": str(event.session_id) if event.session_id else None,
                    "event_type": event.event_type,
                    "target_type": event.target_type,
                    "target_id": str(event.target_id) if event.target_id else None,
                    "result": event.result,
                    "network_context": event.network_context,
                    "correlation_id": event.correlation_id,
                    "details": event.details,
                    "previous_hash": previous_hash,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            expected = hashlib.sha256(canonical.encode()).hexdigest()
            if event.previous_hash != previous_hash or event.event_hash != expected:
                return False, event.id
            previous_hash = event.event_hash
        return True, None
