from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.api.dependencies import RequestIdentity, csrf_guard, current_identity, db_session
from kajovodagmar.api.serializers import model_view
from kajovodagmar.memory.schemas import MemoryCreate, MemorySearch, MemoryUpdate

router = APIRouter(prefix="/memory", tags=["memory"])
FIELDS = (
    "id",
    "content",
    "category",
    "state",
    "origin_type",
    "event_at",
    "valid_from",
    "valid_until",
    "created_at",
    "updated_at",
    "version",
    "deleted_at",
    "purge_after",
    "merged_into_id",
)


class VersionRequest(BaseModel):
    expected_version: int = Field(ge=1)


class MergeRequest(BaseModel):
    source_ids: list[UUID] = Field(min_length=2, max_length=20)
    target: MemoryCreate


@router.post("/search")
async def search(
    payload: MemorySearch,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    ranked = (
        await request.app.state.search.ranked_owner_ids(
            session,
            account_id=identity.account.id,
            owner_type="memory",
            query=payload.query,
            limit=payload.limit,
        )
        if payload.query.strip()
        else []
    )
    rows = await request.app.state.memory.search(session, identity.account.id, payload, ranked)
    return {"items": [model_view(r, *FIELDS) for r in rows], "scope": "global", "count": len(rows)}


@router.post("", status_code=201)
async def create(
    payload: MemoryCreate,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    row = await request.app.state.memory.create(
        session, identity.account.id, payload, identity.audit_context
    )
    return model_view(row, *FIELDS)


@router.get("/{memory_id}")
async def detail(
    memory_id: UUID,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    row = await request.app.state.memory.get(
        session, identity.account.id, memory_id, include_deleted=True
    )
    return model_view(row, *FIELDS)


@router.put("/{memory_id}")
async def update(
    memory_id: UUID,
    payload: MemoryUpdate,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    row = await request.app.state.memory.update(
        session, identity.account.id, memory_id, payload, identity.audit_context
    )
    return model_view(row, *FIELDS)


@router.post("/{memory_id}/confirm")
async def confirm(
    memory_id: UUID,
    payload: VersionRequest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    row = await request.app.state.memory.confirm(
        session, identity.account.id, memory_id, payload.expected_version, identity.audit_context
    )
    return model_view(row, *FIELDS)


@router.delete("/{memory_id}")
async def remove(
    memory_id: UUID,
    payload: VersionRequest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    retention = await request.app.state.setting_value(session, "memory", "soft_delete_days", 30)
    row = await request.app.state.memory.soft_delete(
        session,
        identity.account.id,
        memory_id,
        payload.expected_version,
        int(retention),
        identity.audit_context,
    )
    return model_view(row, *FIELDS)


@router.post("/{memory_id}/restore")
async def restore(
    memory_id: UUID,
    payload: VersionRequest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    row = await request.app.state.memory.restore(
        session, identity.account.id, memory_id, payload.expected_version, identity.audit_context
    )
    return model_view(row, *FIELDS)


@router.post("/merge", status_code=201)
async def merge(
    payload: MergeRequest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    row = await request.app.state.memory.merge(
        session, identity.account.id, payload.source_ids, payload.target, identity.audit_context
    )
    return model_view(row, *FIELDS)
