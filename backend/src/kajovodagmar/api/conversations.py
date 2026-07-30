from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.api.dependencies import RequestIdentity, csrf_guard, db_session
from kajovodagmar.api.serializers import model_view
from kajovodagmar.conversations.schemas import ConversationStart, TranscriptCorrection, UserTurn

router = APIRouter(prefix="/conversations", tags=["conversations"])
CF = (
    "id",
    "state",
    "input_mode",
    "language",
    "title",
    "summary",
    "started_at",
    "ended_at",
    "last_activity_at",
    "message_count",
    "version",
)
MF = (
    "id",
    "conversation_id",
    "sequence",
    "role",
    "content",
    "input_mode",
    "status",
    "interrupted",
    "created_at",
    "finalized_at",
    "version",
)


class EndRequest(BaseModel):
    reason: str = Field(default="user_ended", min_length=3, max_length=80)


@router.post("", status_code=201)
async def start(
    payload: ConversationStart,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    row = await request.app.state.conversations.start(
        session, identity.account.id, payload, identity.audit_context
    )
    return model_view(row, *CF)


@router.post("/{conversation_id}/turns", status_code=201)
async def turn(
    conversation_id: UUID,
    payload: UserTurn,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    message = await request.app.state.conversations.add_user_turn(
        session, identity.account.id, conversation_id, payload, identity.audit_context
    )
    result = await request.app.state.orchestration.answer(
        session, identity.account.id, conversation_id, message.id, identity.audit_context
    )
    return {
        "user": model_view(message, *MF),
        "assistant": model_view(result.message, *MF),
        "run_id": str(result.run_id),
        "decision": {
            "intent": result.decision.intent,
            "result_type": result.decision.result_type,
            "uncertainty": result.decision.uncertainty,
            "sources": [source.model_dump() for source in result.decision.sources],
            "requires_confirmation": result.decision.requires_confirmation,
            "memory_proposal": result.decision.memory_proposal.model_dump()
            if result.decision.memory_proposal
            else None,
        },
        "actions": [
            {
                "id": str(action.id),
                "name": action.name,
                "state": action.state,
                "preview": action.preview,
                "expires_at": action.expires_at.isoformat() if action.expires_at else None,
                "version": action.version,
            }
            for action in result.actions
        ],
    }


@router.put("/messages/{message_id}/transcript")
async def correct(
    message_id: UUID,
    payload: TranscriptCorrection,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    row = await request.app.state.conversations.correct_transcript(
        session, identity.account.id, message_id, payload, identity.audit_context
    )
    return model_view(row, *MF)


@router.post("/{conversation_id}/end")
async def end(
    conversation_id: UUID,
    payload: EndRequest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    row = await request.app.state.conversations.end(
        session, identity.account.id, conversation_id, payload.reason, identity.audit_context
    )
    return model_view(row, *CF)
