from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.api.dependencies import RequestIdentity, csrf_guard, current_identity, db_session
from kajovodagmar.db.models import EncryptedSecret, ProviderConfiguration

router = APIRouter(prefix="/notifications", tags=["notifications"])


class SMTPUpdate(BaseModel):
    display_name: str = Field(default="Odchozí e-mail", min_length=1, max_length=160)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=255)
    password: SecretStr | None = None
    sender: EmailStr
    use_starttls: bool = True


class SMTPTest(BaseModel):
    recipient: EmailStr


@router.get("/email")
async def state(
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    row = await session.scalar(
        select(ProviderConfiguration).where(ProviderConfiguration.provider_type == "smtp")
    )
    if row is None:
        return {"configured": False, "verification_state": "not_configured"}
    secret = await session.get(EncryptedSecret, row.secret_id) if row.secret_id else None
    from urllib.parse import urlparse

    parsed = urlparse(row.base_url)
    return {
        "configured": True,
        "display_name": row.display_name,
        "host": parsed.hostname,
        "port": parsed.port,
        "username": row.capabilities.get("username"),
        "sender": row.capabilities.get("sender"),
        "use_starttls": row.capabilities.get("use_starttls", True),
        "password_present": bool(secret and not secret.revoked_at),
        "password_hint": secret.masked_hint if secret else None,
        "verification_state": row.verification_state,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "version": row.version,
    }


@router.put("/email")
async def save(
    payload: SMTPUpdate,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    row = await request.app.state.notifications.save_smtp(
        session,
        display_name=payload.display_name,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password=payload.password.get_secret_value() if payload.password else None,
        sender=str(payload.sender),
        use_starttls=payload.use_starttls,
        context=identity.audit_context,
    )
    return {"id": str(row.id), "version": row.version, "verification_state": row.verification_state}


@router.post("/email/test")
async def test(
    payload: SMTPTest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    await request.app.state.notifications.test_smtp(
        session, str(payload.recipient), identity.audit_context
    )
    return {"delivered": True}
