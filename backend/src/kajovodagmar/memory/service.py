from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.audit.service import AuditContext, AuditService
from kajovodagmar.db.models import MemoryItem, MemorySource, MemoryVersion, OutboxEvent
from kajovodagmar.errors import ConflictError, DomainError, NotFoundError
from kajovodagmar.memory.schemas import MemoryCreate, MemorySearch, MemoryUpdate
from kajovodagmar.types import utc_now

SECRET_TERMS = ("api key", "api klíč", "password", "heslo", "token", "obnovovací kód", "secret")


def contains_secret_instruction(content: str) -> bool:
    lowered = content.casefold()
    return any(term in lowered for term in SECRET_TERMS)


class MemoryService:
    def __init__(self, audit: AuditService) -> None:
        self.audit = audit

    async def create(
        self, session: AsyncSession, account_id: UUID, request: MemoryCreate, context: AuditContext
    ) -> MemoryItem:
        if contains_secret_instruction(request.content):
            raise DomainError(
                "secret_memory_forbidden",
                "Tajné hodnoty se neukládají do dlouhodobé paměti. "
                "Použijte zabezpečenou správu poskytovatelů.",
                422,
            )
        if request.valid_from and request.valid_until and request.valid_until < request.valid_from:
            raise DomainError("invalid_validity", "Konec platnosti nesmí předcházet začátku.", 422)
        duplicate = await session.scalar(
            select(MemoryItem)
            .where(
                MemoryItem.account_id == account_id,
                MemoryItem.state.in_(["active", "pending_confirmation"]),
                func.lower(MemoryItem.content) == request.content.casefold(),
            )
            .limit(1)
        )
        if duplicate:
            raise ConflictError(
                "Významově totožná položka již existuje.", {"memory_id": str(duplicate.id)}
            )
        state = (
            "active"
            if request.confirmed or request.origin_type in {"explicit_command", "manual"}
            else "pending_confirmation"
        )
        item = MemoryItem(
            account_id=account_id,
            content=request.content.strip(),
            category=request.category,
            state=state,
            origin_type=request.origin_type,
            event_at=request.event_at,
            valid_from=request.valid_from,
            valid_until=request.valid_until,
            original_expression=request.original_expression,
            keywords=sorted(set(k.strip() for k in request.keywords if k.strip())),
            confirmed_at=utc_now() if state == "active" else None,
        )
        session.add(item)
        await session.flush()
        session.add(
            MemoryVersion(
                memory_id=item.id,
                version_number=1,
                content=item.content,
                category=item.category,
                state=item.state,
                change_kind="created",
                changed_by=account_id,
                snapshot=self._snapshot(item),
            )
        )
        session.add(
            MemorySource(
                memory_id=item.id,
                source_type=request.origin_type,
                conversation_id=request.source_conversation_id,
                message_id=request.source_message_id,
                source_excerpt=request.original_expression,
            )
        )
        session.add(
            OutboxEvent(
                aggregate_type="memory",
                aggregate_id=item.id,
                event_type="memory.index_requested",
                payload={"memory_id": str(item.id)},
                sequence=1,
            )
        )
        await self.audit.append(
            session,
            context=context,
            event_type="memory.created",
            result="success",
            target_type="memory_item",
            target_id=item.id,
            details={"category": item.category, "state": item.state},
        )
        await session.refresh(item)
        return item

    async def get(
        self,
        session: AsyncSession,
        account_id: UUID,
        memory_id: UUID,
        include_deleted: bool = False,
    ) -> MemoryItem:
        query = select(MemoryItem).where(
            MemoryItem.id == memory_id, MemoryItem.account_id == account_id
        )
        if not include_deleted:
            query = query.where(MemoryItem.state != "deleted")
        item = await session.scalar(query)
        if item is None:
            raise NotFoundError("Paměťová položka nebyla nalezena.")
        return item

    async def confirm(
        self,
        session: AsyncSession,
        account_id: UUID,
        memory_id: UUID,
        expected_version: int,
        context: AuditContext,
    ) -> MemoryItem:
        item = await session.scalar(
            select(MemoryItem)
            .where(MemoryItem.id == memory_id, MemoryItem.account_id == account_id)
            .with_for_update()
        )
        if item is None:
            raise NotFoundError("Paměťová položka nebyla nalezena.")
        self._version_guard(item, expected_version)
        if item.state != "pending_confirmation":
            raise ConflictError("Položka nečeká na potvrzení.")
        item.state = "active"
        item.confirmed_at = utc_now()
        item.version += 1
        await self._record_version(session, item, account_id, "confirmed")
        await self.audit.append(
            session,
            context=context,
            event_type="memory.confirmed",
            result="success",
            target_id=item.id,
        )
        await session.refresh(item)
        return item

    async def update(
        self,
        session: AsyncSession,
        account_id: UUID,
        memory_id: UUID,
        request: MemoryUpdate,
        context: AuditContext,
    ) -> MemoryItem:
        item = await session.scalar(
            select(MemoryItem)
            .where(MemoryItem.id == memory_id, MemoryItem.account_id == account_id)
            .with_for_update()
        )
        if item is None:
            raise NotFoundError("Paměťová položka nebyla nalezena.")
        self._version_guard(item, request.expected_version)
        if item.state in {"deleted", "merged"}:
            raise ConflictError("Odstraněnou nebo sloučenou položku nelze přímo upravit.")
        if request.content is not None:
            if contains_secret_instruction(request.content):
                raise DomainError(
                    "secret_memory_forbidden",
                    "Tajné hodnoty se neukládají do dlouhodobé paměti.",
                    422,
                )
            item.content = request.content.strip()
        if request.category is not None:
            item.category = request.category
        if request.event_at is not None:
            item.event_at = request.event_at
        if request.valid_from is not None:
            item.valid_from = request.valid_from
        if request.valid_until is not None:
            item.valid_until = request.valid_until
        if request.mark_outdated:
            item.state = "outdated"
        if item.valid_from and item.valid_until and item.valid_until < item.valid_from:
            raise DomainError("invalid_validity", "Konec platnosti nesmí předcházet začátku.", 422)
        item.version += 1
        await self._record_version(session, item, account_id, "updated")
        session.add(
            OutboxEvent(
                aggregate_type="memory",
                aggregate_id=item.id,
                event_type="memory.index_requested",
                payload={"memory_id": str(item.id)},
                sequence=item.version,
            )
        )
        await self.audit.append(
            session,
            context=context,
            event_type="memory.updated",
            result="success",
            target_id=item.id,
            details={"version": item.version, "state": item.state},
        )
        await session.refresh(item)
        return item

    async def soft_delete(
        self,
        session: AsyncSession,
        account_id: UUID,
        memory_id: UUID,
        expected_version: int,
        retention_days: int,
        context: AuditContext,
    ) -> MemoryItem:
        item = await session.scalar(
            select(MemoryItem)
            .where(MemoryItem.id == memory_id, MemoryItem.account_id == account_id)
            .with_for_update()
        )
        if item is None:
            raise NotFoundError("Paměťová položka nebyla nalezena.")
        self._version_guard(item, expected_version)
        if item.state == "deleted":
            return item
        item.state = "deleted"
        item.deleted_at = utc_now()
        item.purge_after = utc_now() + timedelta(days=retention_days)
        item.version += 1
        await self._record_version(session, item, account_id, "deleted")
        await self.audit.append(
            session,
            context=context,
            event_type="memory.deleted",
            result="success",
            target_id=item.id,
            details={"recoverable_until": item.purge_after.isoformat()},
        )
        await session.refresh(item)
        return item

    async def restore(
        self,
        session: AsyncSession,
        account_id: UUID,
        memory_id: UUID,
        expected_version: int,
        context: AuditContext,
    ) -> MemoryItem:
        item = await session.scalar(
            select(MemoryItem)
            .where(MemoryItem.id == memory_id, MemoryItem.account_id == account_id)
            .with_for_update()
        )
        if item is None:
            raise NotFoundError("Paměťová položka nebyla nalezena.")
        self._version_guard(item, expected_version)
        if item.state != "deleted" or not item.purge_after or item.purge_after <= utc_now():
            raise ConflictError("Položku již nelze běžným způsobem obnovit.")
        item.state = "active"
        item.deleted_at = None
        item.purge_after = None
        item.version += 1
        await self._record_version(session, item, account_id, "restored")
        session.add(
            OutboxEvent(
                aggregate_type="memory",
                aggregate_id=item.id,
                event_type="memory.index_requested",
                payload={"memory_id": str(item.id)},
                sequence=item.version,
            )
        )
        await self.audit.append(
            session,
            context=context,
            event_type="memory.restored",
            result="success",
            target_id=item.id,
        )
        await session.refresh(item)
        return item

    async def merge(
        self,
        session: AsyncSession,
        account_id: UUID,
        source_ids: list[UUID],
        target: MemoryCreate,
        context: AuditContext,
    ) -> MemoryItem:
        if len(set(source_ids)) < 2:
            raise DomainError(
                "merge_requires_multiple", "Sloučení vyžaduje nejméně dvě různé položky.", 422
            )
        sources = (
            await session.scalars(
                select(MemoryItem)
                .where(MemoryItem.account_id == account_id, MemoryItem.id.in_(source_ids))
                .with_for_update()
            )
        ).all()
        if len(sources) != len(set(source_ids)) or any(
            i.state not in {"active", "outdated"} for i in sources
        ):
            raise ConflictError(
                "Všechny zdrojové položky musí existovat a být aktivní nebo neaktuální."
            )
        target.confirmed = True
        merged = await self.create(session, account_id, target, context)
        for source in sources:
            source.state = "merged"
            source.merged_into_id = merged.id
            source.version += 1
            await self._record_version(session, source, account_id, "merged")
        await self.audit.append(
            session,
            context=context,
            event_type="memory.merged",
            result="success",
            target_id=merged.id,
            details={"source_ids": [str(i) for i in source_ids]},
        )
        await session.refresh(merged)
        return merged

    async def search(
        self,
        session: AsyncSession,
        account_id: UUID,
        request: MemorySearch,
        ranked_ids: list[UUID] | None = None,
    ) -> list[MemoryItem]:
        clauses = [MemoryItem.account_id == account_id, MemoryItem.state.in_(request.states)]
        if request.categories:
            clauses.append(MemoryItem.category.in_(request.categories))
        if request.from_at:
            clauses.append(
                or_(
                    MemoryItem.event_at >= request.from_at, MemoryItem.created_at >= request.from_at
                )
            )
        if request.to_at:
            clauses.append(
                or_(MemoryItem.event_at <= request.to_at, MemoryItem.created_at <= request.to_at)
            )
        query = select(MemoryItem).where(and_(*clauses))
        if request.query.strip():
            terms = [term for term in request.query.strip().split() if term]
            rank_parts = [
                func.lower(MemoryItem.content).contains(term.casefold()) for term in terms
            ]
            if ranked_ids:
                query = query.where(or_(*rank_parts, MemoryItem.id.in_(ranked_ids)))
                rank_order = case(
                    {value: index for index, value in enumerate(ranked_ids)},
                    value=MemoryItem.id,
                    else_=len(ranked_ids) + 1,
                )
                query = query.order_by(rank_order, MemoryItem.updated_at.desc(), MemoryItem.id)
            else:
                query = query.where(or_(*rank_parts)).order_by(
                    MemoryItem.updated_at.desc(), MemoryItem.id
                )
        else:
            query = query.order_by(MemoryItem.updated_at.desc(), MemoryItem.id)
        return list((await session.scalars(query.limit(request.limit))).all())

    @staticmethod
    def _version_guard(item: MemoryItem, expected: int) -> None:
        if item.version != expected:
            raise ConflictError(
                "Paměťová položka byla mezitím změněna.",
                {"expected_version": expected, "actual_version": item.version},
            )

    @staticmethod
    def _snapshot(item: MemoryItem) -> dict[str, Any]:
        return {
            "content": item.content,
            "category": item.category,
            "state": item.state,
            "event_at": item.event_at.isoformat() if item.event_at else None,
            "valid_from": item.valid_from.isoformat() if item.valid_from else None,
            "valid_until": item.valid_until.isoformat() if item.valid_until else None,
            "keywords": list(item.keywords),
        }

    async def _record_version(
        self, session: AsyncSession, item: MemoryItem, account_id: UUID, change_kind: str
    ) -> None:
        session.add(
            MemoryVersion(
                memory_id=item.id,
                version_number=item.version,
                content=item.content,
                category=item.category,
                state=item.state,
                change_kind=change_kind,
                changed_by=account_id,
                snapshot=self._snapshot(item),
            )
        )
