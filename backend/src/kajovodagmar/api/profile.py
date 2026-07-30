from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.api.dependencies import (
    RequestIdentity,
    csrf_guard,
    current_identity,
    db_session,
    network_context,
)
from kajovodagmar.audit.service import AuditContext
from kajovodagmar.db.models import AdministratorProfile

router = APIRouter(prefix="/profile", tags=["profile"])


class EmailChange(BaseModel):
    email: EmailStr
    current_password: SecretStr


class EmailVerification(BaseModel):
    token: SecretStr


@router.get("")
async def profile(
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    row = await session.scalar(
        select(AdministratorProfile).where(AdministratorProfile.account_id == identity.account.id)
    )
    return {
        "username": identity.account.username,
        "display_name": row.display_name if row else "",
        "email": row.email if row else None,
        "pending_email": row.pending_email if row else None,
        "email_state": row.email_state if row else "not_set",
        "email_verified_at": row.email_verified_at.isoformat()
        if row and row.email_verified_at
        else None,
        "locale": row.locale if row else "cs-CZ",
        "timezone": row.timezone if row else "Europe/Prague",
        "version": row.version if row else 0,
    }


@router.post("/email/change")
async def change_email(
    payload: EmailChange,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    token = await request.app.state.identity.begin_email_change(
        session,
        identity.account,
        str(payload.email),
        payload.current_password.get_secret_value(),
        identity.audit_context,
    )
    await request.app.state.notifications.send_email_verification(
        session, str(payload.email), token
    )
    return {
        "pending": True,
        "message": "Na novou adresu byl odeslán ověřovací odkaz s platností 30 minut.",
    }


@router.post("/email/verify")
async def verify_email(
    payload: EmailVerification, request: Request, session: AsyncSession = Depends(db_session)
):
    context = AuditContext(
        "email_verification",
        network_context=network_context(request),
        correlation_id=request.state.correlation_id,
    )
    row = await request.app.state.identity.complete_email_verification(
        session, payload.token.get_secret_value(), context
    )
    return {"verified": True, "email": row.email}
