from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.audit.service import AuditContext, AuditService
from kajovodagmar.db.models import (
    ApplicationSetting,
    AuditEvent,
    Conversation,
    ConversationMessage,
    ExportRecord,
    MemoryItem,
    MemorySource,
    MemoryVersion,
)
from kajovodagmar.errors import ConflictError, NotFoundError
from kajovodagmar.jobs.service import JobService
from kajovodagmar.types import utc_now


class ExportService:
    def __init__(self, audit: AuditService, jobs: JobService, export_root: Path) -> None:
        self.audit = audit
        self.jobs = jobs
        self.export_root = export_root.resolve()

    async def request(
        self,
        session: AsyncSession,
        account_id: UUID,
        *,
        kind: str,
        format: str,
        scope: dict[str, Any],
        context: AuditContext,
    ) -> ExportRecord:
        if kind not in {"history", "memory", "configuration", "audit"}:
            raise ConflictError("Tento druh exportu není podporován.")
        if format not in {"json", "markdown"}:
            raise ConflictError("Export lze vytvořit jako JSON nebo Markdown.")
        record = ExportRecord(
            account_id=account_id,
            kind=kind,
            state="queued",
            format=format,
            scope=scope,
            expires_at=utc_now() + timedelta(hours=24),
        )
        session.add(record)
        await session.flush()
        await self.jobs.enqueue(
            session,
            "export_generate",
            {"export_id": str(record.id)},
            correlation_id=context.correlation_id,
        )
        await self.audit.append(
            session,
            context=context,
            event_type="export.requested",
            result="success",
            target_type="export_record",
            target_id=record.id,
            details={"kind": kind, "format": format},
        )
        return record

    async def list(self, session: AsyncSession, account_id: UUID) -> list[ExportRecord]:
        return list(
            (
                await session.scalars(
                    select(ExportRecord)
                    .where(ExportRecord.account_id == account_id)
                    .order_by(ExportRecord.created_at.desc())
                    .limit(100)
                )
            ).all()
        )

    async def get(self, session: AsyncSession, account_id: UUID, export_id: UUID) -> ExportRecord:
        row = await session.scalar(
            select(ExportRecord).where(
                ExportRecord.id == export_id, ExportRecord.account_id == account_id
            )
        )
        if row is None:
            raise NotFoundError("Export nebyl nalezen.")
        return row

    async def generate(self, session: AsyncSession, export_id: UUID) -> None:
        record = await session.scalar(
            select(ExportRecord).where(ExportRecord.id == export_id).with_for_update()
        )
        if record is None or record.state == "completed":
            return
        if record.expires_at and record.expires_at <= utc_now():
            record.state = "expired"
            return
        record.state = "running"
        payload = await self._payload(session, record)
        extension = "json" if record.format == "json" else "md"
        account_dir = (self.export_root / str(record.account_id)).resolve()
        if self.export_root not in account_dir.parents:
            raise RuntimeError("Neplatná cesta exportu.")
        account_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = (account_dir / f"{record.id}.{extension}").resolve()
        if account_dir not in target.parents:
            raise RuntimeError("Neplatná cesta exportního souboru.")
        data = (
            json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
            if record.format == "json"
            else self._markdown(record.kind, payload).encode("utf-8")
        )
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.chmod(0o600)
        temporary.replace(target)
        record.file_path = str(target)
        record.file_digest = hashlib.sha256(data).hexdigest()
        record.state = "completed"
        record.completed_at = utc_now()
        record.version += 1

    async def purge_expired(self, session: AsyncSession) -> int:
        rows = list(
            (
                await session.scalars(
                    select(ExportRecord).where(
                        ExportRecord.expires_at <= utc_now(),
                        ExportRecord.state.in_(["queued", "running", "completed", "failed"]),
                    )
                )
            ).all()
        )
        removed = 0
        for row in rows:
            if row.file_path:
                path = Path(row.file_path).resolve()
                if self.export_root in path.parents and path.exists():
                    path.unlink()
                    removed += 1
            row.state = "expired"
            row.file_path = None
            row.version += 1
        return removed

    async def _payload(self, session: AsyncSession, record: ExportRecord) -> dict[str, Any]:
        if record.kind == "history":
            conversations = list(
                (
                    await session.scalars(
                        select(Conversation)
                        .where(Conversation.account_id == record.account_id)
                        .order_by(Conversation.started_at)
                    )
                ).all()
            )
            items = []
            for conversation in conversations:
                messages = list(
                    (
                        await session.scalars(
                            select(ConversationMessage)
                            .where(ConversationMessage.conversation_id == conversation.id)
                            .order_by(ConversationMessage.sequence)
                        )
                    ).all()
                )
                items.append(
                    {
                        "id": str(conversation.id),
                        "state": conversation.state,
                        "title": conversation.title,
                        "summary": conversation.summary,
                        "summary_source": conversation.summary_source,
                        "started_at": conversation.started_at,
                        "ended_at": conversation.ended_at,
                        "continuation_of_id": str(conversation.continuation_of_id)
                        if conversation.continuation_of_id
                        else None,
                        "version": conversation.version,
                        "messages": [
                            {
                                "id": str(message.id),
                                "sequence": message.sequence,
                                "role": message.role,
                                "content": message.content,
                                "status": message.status,
                                "interrupted": message.interrupted,
                                "created_at": message.created_at,
                                "version": message.version,
                            }
                            for message in messages
                        ],
                    }
                )
            return {
                "schema_version": 1,
                "kind": "history",
                "generated_at": utc_now(),
                "items": items,
            }
        if record.kind == "memory":
            memories = list(
                (
                    await session.scalars(
                        select(MemoryItem)
                        .where(MemoryItem.account_id == record.account_id)
                        .order_by(MemoryItem.created_at)
                    )
                ).all()
            )
            items = []
            for memory in memories:
                versions = list(
                    (
                        await session.scalars(
                            select(MemoryVersion)
                            .where(MemoryVersion.memory_id == memory.id)
                            .order_by(MemoryVersion.version_number)
                        )
                    ).all()
                )
                sources = list(
                    (
                        await session.scalars(
                            select(MemorySource).where(MemorySource.memory_id == memory.id)
                        )
                    ).all()
                )
                items.append(
                    {
                        "id": str(memory.id),
                        "content": memory.content,
                        "category": memory.category,
                        "state": memory.state,
                        "origin_type": memory.origin_type,
                        "event_at": memory.event_at,
                        "valid_from": memory.valid_from,
                        "valid_until": memory.valid_until,
                        "created_at": memory.created_at,
                        "updated_at": memory.updated_at,
                        "version": memory.version,
                        "versions": [
                            {
                                "number": version.version_number,
                                "content": version.content,
                                "category": version.category,
                                "state": version.state,
                                "changed_at": version.changed_at,
                            }
                            for version in versions
                        ],
                        "sources": [
                            {
                                "type": source.source_type,
                                "conversation_id": str(source.conversation_id)
                                if source.conversation_id
                                else None,
                                "message_id": str(source.message_id) if source.message_id else None,
                                "quoted_text": source.source_excerpt,
                            }
                            for source in sources
                        ],
                    }
                )
            return {
                "schema_version": 1,
                "kind": "memory",
                "generated_at": utc_now(),
                "items": items,
            }
        if record.kind == "audit":
            query = select(AuditEvent).order_by(AuditEvent.id)
            area = record.scope.get("area")
            result = record.scope.get("result")
            correlation_id = record.scope.get("correlation_id")
            if isinstance(area, str) and area:
                query = query.where(AuditEvent.event_type.startswith(f"{area}."))
            if isinstance(result, str) and result:
                query = query.where(AuditEvent.result == result)
            if isinstance(correlation_id, str) and correlation_id:
                query = query.where(AuditEvent.correlation_id == correlation_id)
            audit_events = list((await session.scalars(query)).all())
            return {
                "schema_version": 1,
                "kind": "audit",
                "generated_at": utc_now(),
                "filters": {
                    "area": area,
                    "result": result,
                    "correlation_id": correlation_id,
                },
                "items": [
                    {
                        "id": event.id,
                        "occurred_at": event.occurred_at,
                        "event_name": event.event_type,
                        "actor_type": event.actor_type,
                        "actor_id": str(event.actor_id) if event.actor_id else None,
                        "target_type": event.target_type,
                        "target_id": str(event.target_id) if event.target_id else None,
                        "result": event.result,
                        "correlation_id": event.correlation_id,
                        "details": event.details,
                        "event_hash": event.event_hash,
                    }
                    for event in audit_events
                ],
            }
        settings = list((await session.scalars(select(ApplicationSetting))).all())
        return {
            "schema_version": 1,
            "kind": "configuration",
            "generated_at": utc_now(),
            "items": [
                {
                    "area": setting.area,
                    "key": setting.key,
                    "value": setting.value,
                    "schema_version": setting.schema_version,
                    "version": setting.version,
                }
                for setting in settings
                if "secret" not in setting.key.casefold()
                and "password" not in setting.key.casefold()
            ],
        }

    @staticmethod
    def _markdown(kind: str, payload: dict[str, Any]) -> str:
        lines = [f"# Export KájovoDagmar – {kind}", "", f"Vytvořeno: {payload['generated_at']}", ""]
        for item in payload.get("items", []):
            heading = item.get("title") or item.get("content") or item.get("key") or item.get("id")
            lines.append(f"## {heading}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(item, ensure_ascii=False, indent=2, default=str))
            lines.append("```")
            lines.append("")
        return "\n".join(lines)
