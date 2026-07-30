from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.api.dependencies import RequestIdentity, csrf_guard, current_identity, db_session
from kajovodagmar.db.models import OrchestrationRun, ToolAction
from kajovodagmar.errors import NotFoundError

router = APIRouter(prefix="/orchestration", tags=["orchestration"])


class ConfirmActionRequest(BaseModel):
    expected_version: int = Field(ge=1)


def action_view(action: ToolAction) -> dict[str, object]:
    return {
        "id": str(action.id),
        "run_id": str(action.run_id),
        "name": action.name,
        "state": action.state,
        "preview": action.preview,
        "confirmation_required": action.confirmation_required,
        "expires_at": action.expires_at.isoformat() if action.expires_at else None,
        "result": action.result,
        "error_code": action.error_code,
        "version": action.version,
    }


@router.get("/runs/{run_id}")
async def run_detail(
    run_id: UUID,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    run = await session.scalar(
        select(OrchestrationRun).where(
            OrchestrationRun.id == run_id,
            OrchestrationRun.account_id == identity.account.id,
        )
    )
    if run is None:
        raise NotFoundError("Orchestration run nebyl nalezen.")
    actions = list(
        (
            await session.scalars(
                select(ToolAction)
                .where(ToolAction.run_id == run.id)
                .order_by(ToolAction.created_at)
            )
        ).all()
    )
    return {
        "id": str(run.id),
        "conversation_id": str(run.conversation_id),
        "source_message_id": str(run.source_message_id),
        "response_message_id": str(run.response_message_id) if run.response_message_id else None,
        "state": run.state,
        "intent": run.intent,
        "decision": run.decision,
        "attempt_count": run.attempt_count,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "cancelled_at": run.cancelled_at.isoformat() if run.cancelled_at else None,
        "error_code": run.error_code,
        "version": run.version,
        "actions": [action_view(action) for action in actions],
    }


@router.post("/actions/{action_id}/confirm")
async def confirm_action(
    action_id: UUID,
    payload: ConfirmActionRequest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    action = await request.app.state.orchestration.confirm_action(
        session,
        account_id=identity.account.id,
        action_id=action_id,
        expected_action_version=payload.expected_version,
        context=identity.audit_context,
    )
    return action_view(action)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: UUID,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    run = await request.app.state.orchestration.cancel_run(
        session,
        account_id=identity.account.id,
        run_id=run_id,
        context=identity.audit_context,
    )
    return {"id": str(run.id), "state": run.state, "version": run.version}
