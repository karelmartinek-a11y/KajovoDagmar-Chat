from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.audit.service import AuditContext, AuditService
from kajovodagmar.db.models import (
    Conversation,
    ConversationLink,
    ConversationMessage,
    ConversationSummary,
)
from kajovodagmar.errors import ConflictError, NotFoundError
from kajovodagmar.history.schemas import HistorySearch, MetadataUpdate
from kajovodagmar.types import utc_now


class HistoryService:
    def __init__(self, audit: AuditService) -> None:
        self.audit = audit

    async def search(
        self,
        session: AsyncSession,
        account_id: UUID,
        request: HistorySearch,
        ranked_ids: list[UUID] | None = None,
    ) -> list[Conversation]:
        clauses = [
            Conversation.account_id == account_id,
            Conversation.state.in_(request.states),
            Conversation.deleted_at.is_(None),
        ]
        if request.from_at:
            clauses.append(Conversation.last_activity_at >= request.from_at)
        if request.to_at:
            clauses.append(Conversation.last_activity_at <= request.to_at)
        if request.query.strip():
            term = f"%{request.query.strip()}%"
            matching_messages = select(ConversationMessage.conversation_id).where(
                ConversationMessage.content.ilike(term)
            )
            conditions = [
                Conversation.title.ilike(term),
                Conversation.summary.ilike(term),
                Conversation.id.in_(matching_messages),
            ]
            if ranked_ids:
                conditions.append(Conversation.id.in_(ranked_ids))
            clauses.append(or_(*conditions))
        query = select(Conversation).where(and_(*clauses))
        if request.query.strip() and ranked_ids:
            rank_order = case(
                {value: index for index, value in enumerate(ranked_ids)},
                value=Conversation.id,
                else_=len(ranked_ids) + 1,
            )
            query = query.order_by(
                rank_order, Conversation.last_activity_at.desc(), Conversation.id
            )
        else:
            query = query.order_by(Conversation.last_activity_at.desc(), Conversation.id)
        query = query.offset(request.offset).limit(request.limit)
        return list((await session.scalars(query)).all())

    async def detail(
        self,
        session: AsyncSession,
        account_id: UUID,
        conversation_id: UUID,
        include_deleted: bool = False,
    ) -> tuple[Conversation, list[ConversationMessage]]:
        query = select(Conversation).where(
            Conversation.id == conversation_id, Conversation.account_id == account_id
        )
        if not include_deleted:
            query = query.where(Conversation.deleted_at.is_(None))
        conversation = await session.scalar(query)
        if conversation is None:
            raise NotFoundError("Konverzace nebyla nalezena.")
        messages = list(
            (
                await session.scalars(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == conversation.id)
                    .order_by(ConversationMessage.sequence)
                )
            ).all()
        )
        return conversation, messages

    async def update_metadata(
        self,
        session: AsyncSession,
        account_id: UUID,
        conversation_id: UUID,
        request: MetadataUpdate,
        context: AuditContext,
    ) -> Conversation:
        row = await session.scalar(
            select(Conversation)
            .where(Conversation.id == conversation_id, Conversation.account_id == account_id)
            .with_for_update()
        )
        if row is None:
            raise NotFoundError("Konverzace nebyla nalezena.")
        if row.version != request.expected_version:
            raise ConflictError(
                "Konverzace byla mezitím změněna.",
                {"expected_version": request.expected_version, "actual_version": row.version},
            )
        if request.title is not None:
            row.title = request.title.strip()
            row.title_source = "manual"
        if request.summary is not None:
            row.summary = request.summary.strip()
            row.summary_source = "manual"
        row.version += 1
        session.add(
            ConversationSummary(
                conversation_id=row.id,
                revision_number=row.version,
                title=row.title or "Rozhovor",
                summary=row.summary or "Bez shrnutí",
                source="manual",
            )
        )
        await self.audit.append(
            session,
            context=context,
            event_type="history.metadata_changed",
            result="success",
            target_id=row.id,
            details={"version": row.version},
        )
        return row

    async def continue_from(
        self, session: AsyncSession, account_id: UUID, conversation_id: UUID, context: AuditContext
    ) -> Conversation:
        original, _ = await self.detail(session, account_id, conversation_id)
        new = Conversation(
            account_id=account_id,
            state="active",
            input_mode="voice",
            language=original.language,
            continuation_of_id=original.id,
        )
        session.add(new)
        await session.flush()
        session.add(
            ConversationLink(source_id=original.id, target_id=new.id, relation="continued_by")
        )
        await self.audit.append(
            session,
            context=context,
            event_type="history.continued",
            result="success",
            target_id=new.id,
            details={"source_id": str(original.id)},
        )
        return new

    async def soft_delete(
        self,
        session: AsyncSession,
        account_id: UUID,
        conversation_id: UUID,
        expected_version: int,
        retention_days: int,
        context: AuditContext,
    ) -> Conversation:
        row = await session.scalar(
            select(Conversation)
            .where(Conversation.id == conversation_id, Conversation.account_id == account_id)
            .with_for_update()
        )
        if row is None:
            raise NotFoundError("Konverzace nebyla nalezena.")
        if row.version != expected_version:
            raise ConflictError("Konverzace byla mezitím změněna.")
        row.deleted_at = utc_now()
        row.purge_after = utc_now() + timedelta(days=retention_days)
        row.state = "deleted"
        row.version += 1
        await self.audit.append(
            session,
            context=context,
            event_type="history.deleted",
            result="success",
            target_id=row.id,
            details={"recoverable_until": row.purge_after.isoformat()},
        )
        return row

    async def restore(
        self,
        session: AsyncSession,
        account_id: UUID,
        conversation_id: UUID,
        expected_version: int,
        context: AuditContext,
    ) -> Conversation:
        row = await session.scalar(
            select(Conversation)
            .where(Conversation.id == conversation_id, Conversation.account_id == account_id)
            .with_for_update()
        )
        if row is None:
            raise NotFoundError("Konverzace nebyla nalezena.")
        if row.version != expected_version:
            raise ConflictError("Konverzace byla mezitím změněna.")
        if not row.deleted_at or not row.purge_after or row.purge_after <= utc_now():
            raise ConflictError("Konverzaci již nelze běžným způsobem obnovit.")
        row.deleted_at = None
        row.purge_after = None
        row.state = "completed" if row.ended_at else "interrupted"
        row.version += 1
        await self.audit.append(
            session,
            context=context,
            event_type="history.restored",
            result="success",
            target_id=row.id,
        )
        return row
