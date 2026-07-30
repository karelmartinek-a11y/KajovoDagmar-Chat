from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.api.dependencies import RequestIdentity, csrf_guard, current_identity, db_session
from kajovodagmar.api.serializers import model_view
from kajovodagmar.history.schemas import HistorySearch, MetadataUpdate

router = APIRouter(prefix="/history", tags=["history"])
CONVERSATION_FIELDS = (
    "id",
    "state",
    "input_mode",
    "language",
    "title",
    "title_source",
    "summary",
    "summary_source",
    "started_at",
    "ended_at",
    "last_activity_at",
    "end_reason",
    "continuation_of_id",
    "deleted_at",
    "purge_after",
    "message_count",
    "version",
)
MESSAGE_FIELDS = (
    "id",
    "sequence",
    "role",
    "content",
    "input_mode",
    "status",
    "interrupted",
    "audio_played_until_ms",
    "created_at",
    "finalized_at",
    "version",
)


class VersionRequest(BaseModel):
    expected_version: int = Field(ge=1)


@router.post("/search")
async def search(
    payload: HistorySearch,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    ranked = (
        await request.app.state.search.ranked_owner_ids(
            session,
            account_id=identity.account.id,
            owner_type="conversation",
            query=payload.query,
            limit=payload.limit + payload.offset,
        )
        if payload.query.strip()
        else []
    )
    rows = await request.app.state.history.search(session, identity.account.id, payload, ranked)
    return {
        "items": [model_view(r, *CONVERSATION_FIELDS) for r in rows],
        "scope": "global",
        "count": len(rows),
    }


@router.get("/{conversation_id}")
async def detail(
    conversation_id: UUID,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    conversation, messages = await request.app.state.history.detail(
        session, identity.account.id, conversation_id, include_deleted=True
    )
    return {
        "conversation": model_view(conversation, *CONVERSATION_FIELDS),
        "messages": [model_view(m, *MESSAGE_FIELDS) for m in messages],
    }


@router.put("/{conversation_id}/metadata")
async def update_metadata(
    conversation_id: UUID,
    payload: MetadataUpdate,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    row = await request.app.state.history.update_metadata(
        session, identity.account.id, conversation_id, payload, identity.audit_context
    )
    return model_view(row, *CONVERSATION_FIELDS)


@router.post("/{conversation_id}/continue", status_code=201)
async def continue_from(
    conversation_id: UUID,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    row = await request.app.state.history.continue_from(
        session, identity.account.id, conversation_id, identity.audit_context
    )
    return model_view(row, *CONVERSATION_FIELDS)


@router.delete("/{conversation_id}")
async def remove(
    conversation_id: UUID,
    payload: VersionRequest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    retention = await request.app.state.setting_value(session, "history", "soft_delete_days", 30)
    row = await request.app.state.history.soft_delete(
        session,
        identity.account.id,
        conversation_id,
        payload.expected_version,
        int(retention),
        identity.audit_context,
    )
    return model_view(row, *CONVERSATION_FIELDS)


@router.post("/{conversation_id}/restore")
async def restore(
    conversation_id: UUID,
    payload: VersionRequest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    row = await request.app.state.history.restore(
        session,
        identity.account.id,
        conversation_id,
        payload.expected_version,
        identity.audit_context,
    )
    return model_view(row, *CONVERSATION_FIELDS)
