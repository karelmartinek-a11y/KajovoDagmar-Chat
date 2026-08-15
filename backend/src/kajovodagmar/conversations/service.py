from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.audit.service import AuditContext, AuditService
from kajovodagmar.conversations.schemas import ConversationStart, TranscriptCorrection, UserTurn
from kajovodagmar.db.models import (
    Conversation,
    ConversationLink,
    ConversationMessage,
    MessageRevision,
    OutboxEvent,
)
from kajovodagmar.errors import ConflictError, NotFoundError
from kajovodagmar.types import utc_now


class ConversationService:
    def __init__(self, audit: AuditService) -> None:
        self.audit = audit

    async def start(
        self,
        session: AsyncSession,
        account_id: UUID,
        request: ConversationStart,
        context: AuditContext,
    ) -> Conversation:
        if request.continuation_of_id:
            original = await session.scalar(
                select(Conversation).where(
                    Conversation.id == request.continuation_of_id,
                    Conversation.account_id == account_id,
                    Conversation.deleted_at.is_(None),
                )
            )
            if original is None:
                raise NotFoundError("Původní konverzace nebyla nalezena.")
        row = Conversation(
            account_id=account_id,
            state="active",
            input_mode=request.input_mode,
            language=request.language,
            continuation_of_id=request.continuation_of_id,
        )
        session.add(row)
        await session.flush()
        if request.continuation_of_id:
            session.add(
                ConversationLink(
                    source_id=request.continuation_of_id, target_id=row.id, relation="continued_by"
                )
            )
        await self.audit.append(
            session,
            context=context,
            event_type="conversation.started",
            result="success",
            target_id=row.id,
            details={
                "input_mode": request.input_mode,
                "continuation": bool(request.continuation_of_id),
            },
        )
        return row

    async def add_user_turn(
        self,
        session: AsyncSession,
        account_id: UUID,
        conversation_id: UUID,
        request: UserTurn,
        context: AuditContext,
    ) -> ConversationMessage:
        conversation = await session.scalar(
            select(Conversation)
            .where(Conversation.id == conversation_id, Conversation.account_id == account_id)
            .with_for_update()
        )
        if conversation is None:
            raise NotFoundError("Konverzace nebyla nalezena.")
        if conversation.state != "active":
            raise ConflictError("Do uzavřené konverzace nelze přidat repliku.")
        request_hash = hashlib.sha256(
            json.dumps(
                {
                    "content": request.content.strip(),
                    "input_mode": request.input_mode,
                    "language": request.language,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        existing = await session.scalar(
            select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.idempotency_key == request.idempotency_key,
            )
        )
        if existing:
            if getattr(existing, "request_hash", None) and existing.request_hash != request_hash:
                raise ConflictError("Idempotency klíč byl použit pro jiný požadavek.")
            return existing
        sequence = (
            int(
                await session.scalar(
                    select(func.coalesce(func.max(ConversationMessage.sequence), 0)).where(
                        ConversationMessage.conversation_id == conversation_id
                    )
                )
            )
            + 1
        )
        message = ConversationMessage(
            conversation_id=conversation_id,
            sequence=sequence,
            role="user",
            content=request.content.strip(),
            input_mode=request.input_mode,
            status="final",
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            finalized_at=utc_now(),
        )
        session.add(message)
        conversation.message_count += 1
        conversation.last_activity_at = utc_now()
        conversation.version += 1
        await session.flush()
        session.add(
            OutboxEvent(
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                event_type="conversation.user_turn_finalized",
                payload={"conversation_id": str(conversation.id), "message_id": str(message.id)},
                sequence=conversation.message_count,
            )
        )
        await self.audit.append(
            session,
            context=context,
            event_type="conversation.user_turn_added",
            result="success",
            target_id=message.id,
            details={"conversation_id": str(conversation.id), "sequence": sequence},
        )
        return message

    async def add_assistant_turn(
        self,
        session: AsyncSession,
        conversation_id: UUID,
        content: str,
        idempotency_key: str,
        run_id: UUID,
        interrupted: bool = False,
    ) -> ConversationMessage:
        conversation = await session.scalar(
            select(Conversation).where(Conversation.id == conversation_id).with_for_update()
        )
        if conversation is None:
            raise NotFoundError("Konverzace nebyla nalezena.")
        existing = await session.scalar(
            select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.idempotency_key == idempotency_key,
            )
        )
        if existing:
            return existing
        sequence = (
            int(
                await session.scalar(
                    select(func.coalesce(func.max(ConversationMessage.sequence), 0)).where(
                        ConversationMessage.conversation_id == conversation_id
                    )
                )
            )
            + 1
        )
        message = ConversationMessage(
            conversation_id=conversation_id,
            sequence=sequence,
            role="assistant",
            content=content,
            input_mode="generated",
            status="interrupted" if interrupted else "final",
            idempotency_key=idempotency_key,
            response_run_id=run_id,
            interrupted=interrupted,
            finalized_at=utc_now(),
        )
        session.add(message)
        conversation.message_count += 1
        conversation.last_activity_at = utc_now()
        conversation.version += 1
        await session.flush()
        return message

    async def correct_transcript(
        self,
        session: AsyncSession,
        account_id: UUID,
        message_id: UUID,
        request: TranscriptCorrection,
        context: AuditContext,
    ) -> ConversationMessage:
        message = await session.scalar(
            select(ConversationMessage)
            .join(Conversation)
            .where(
                ConversationMessage.id == message_id,
                Conversation.account_id == account_id,
                ConversationMessage.role == "user",
            )
            .with_for_update()
        )
        if message is None:
            raise NotFoundError("Uživatelská replika nebyla nalezena.")
        if message.version != request.expected_message_version:
            raise ConflictError("Replika byla mezitím změněna.")
        original = message.content
        message.content = request.corrected_content.strip()
        message.version += 1
        session.add(
            MessageRevision(
                message_id=message.id,
                revision_number=message.version,
                original_content=original,
                revised_content=message.content,
                reason="transcript_correction",
                created_by=account_id,
            )
        )
        await self.audit.append(
            session,
            context=context,
            event_type="conversation.transcript_corrected",
            result="success",
            target_id=message.id,
            details={
                "version": message.version,
                "new_answer_requested": request.request_new_answer,
            },
        )
        if request.request_new_answer:
            session.add(
                OutboxEvent(
                    aggregate_type="conversation",
                    aggregate_id=message.conversation_id,
                    event_type="conversation.corrected_turn_reprocess_requested",
                    payload={"message_id": str(message.id)},
                    sequence=message.sequence,
                )
            )
        return message

    async def end(
        self,
        session: AsyncSession,
        account_id: UUID,
        conversation_id: UUID,
        reason: str,
        context: AuditContext,
    ) -> Conversation:
        row = await session.scalar(
            select(Conversation)
            .where(Conversation.id == conversation_id, Conversation.account_id == account_id)
            .with_for_update()
        )
        if row is None:
            raise NotFoundError("Konverzace nebyla nalezena.")
        if row.state == "active":
            row.state = "completed" if reason == "user_ended" else "interrupted"
            row.end_reason = reason
            row.ended_at = utc_now()
            row.last_activity_at = utc_now()
            row.version += 1
            session.add(
                OutboxEvent(
                    aggregate_type="conversation",
                    aggregate_id=row.id,
                    event_type="conversation.closed",
                    payload={"conversation_id": str(row.id)},
                    sequence=row.message_count + 1,
                )
            )
            await self.audit.append(
                session,
                context=context,
                event_type="conversation.ended",
                result="success",
                target_id=row.id,
                details={"reason": reason, "state": row.state},
            )
        return row
