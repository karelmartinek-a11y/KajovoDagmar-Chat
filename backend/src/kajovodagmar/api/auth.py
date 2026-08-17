from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
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
from kajovodagmar.db.models import (
    AdministratorAccount,
    AdministratorProfile,
    AuthSession,
    ServiceAccessNotice,
)
from kajovodagmar.errors import DomainError
from kajovodagmar.identity.schemas import (
    ChangePasswordRequest,
    InitializeRequest,
    LoginRequest,
    PasswordResetComplete,
    PasswordResetRequest,
)
from kajovodagmar.security.voice_service import acknowledge_notice
from kajovodagmar.types import utc_now

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/state")
async def auth_state(request: Request, session: AsyncSession = Depends(db_session)):
    state = await request.app.state.identity.initialization_state(session)
    account = await session.scalar(select(AdministratorAccount).limit(1))
    return {
        "instance_state": state,
        "initialized": account is not None,
        "username": account.username if account else "Karmar78",
    }


@router.post("/initialize", status_code=201)
async def initialize(
    payload: InitializeRequest, request: Request, session: AsyncSession = Depends(db_session)
):
    context = AuditContext(
        "operator",
        network_context=network_context(request),
        correlation_id=request.state.correlation_id,
    )
    account = await request.app.state.identity.initialize(session, payload, context)
    await session.commit()
    return {"account_id": str(account.id), "state": account.state, "username": account.username}


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(db_session),
):
    context = AuditContext(
        "anonymous",
        network_context=network_context(request),
        correlation_id=request.state.correlation_id,
    )
    account = await request.app.state.identity.authenticate(
        session, payload.username, payload.password.get_secret_value(), context
    )
    idle = await request.app.state.setting_value(session, "security", "session_idle_minutes", 30)
    new = await request.app.state.identity.create_session(session, account, context, int(idle))
    response.set_cookie(
        "__Host-kajovodagmar_session",
        new.cookie_value,
        secure=request.app.state.settings.environment in {"test", "production"},
        httponly=True,
        samesite="strict",
        path="/",
        max_age=43200,
    )
    return {
        "authenticated": True,
        "csrf_token": new.csrf_value,
        "session_id": str(new.record.id),
        "expires_at": new.record.expires_at.isoformat(),
    }


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    await request.app.state.identity.revoke_session(
        session, identity.auth_session, "user_logout", identity.audit_context
    )
    response.delete_cookie(
        "__Host-kajovodagmar_session",
        secure=request.app.state.settings.environment in {"test", "production"},
        httponly=True,
        samesite="strict",
        path="/",
    )


@router.get("/me")
async def me(
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    profile = await session.scalar(
        select(AdministratorProfile).where(AdministratorProfile.account_id == identity.account.id)
    )
    notice = await session.scalar(
        select(ServiceAccessNotice)
        .where(
            ServiceAccessNotice.account_id == identity.account.id,
            ServiceAccessNotice.acknowledged_at.is_(None),
        )
        .order_by(ServiceAccessNotice.occurred_at.desc())
    )
    return {
        "id": str(identity.account.id),
        "username": identity.account.username,
        "state": identity.account.state,
        "profile": {
            "display_name": profile.display_name if profile else "",
            "email": profile.email if profile else None,
            "email_state": profile.email_state if profile else "not_set",
        },
        "service_access_notice": (
            {
                "id": str(notice.id),
                "occurred_at": notice.occurred_at.isoformat(),
                "result": notice.result,
                "endpoint": notice.endpoint,
                "network_context": notice.network_context,
                "correlation_id": notice.correlation_id,
            }
            if notice
            else None
        ),
    }


@router.post("/service-access-notices/{notice_id}/ack", status_code=204)
async def acknowledge_service_access_notice(
    notice_id: str,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    from uuid import UUID

    try:
        parsed = UUID(notice_id)
    except ValueError as exc:
        raise DomainError(
            "invalid_notice_id", "Identifikátor upozornění není platný.", 422
        ) from exc
    await acknowledge_notice(session, identity.account.id, parsed)


@router.get("/sessions")
async def sessions(
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    rows = (
        await session.scalars(
            select(AuthSession)
            .where(
                AuthSession.account_id == identity.account.id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > utc_now(),
                AuthSession.absolute_expires_at > utc_now(),
            )
            .order_by(AuthSession.last_activity_at.desc())
        )
    ).all()
    return {
        "items": [
            {
                "id": str(r.id),
                "created_at": r.created_at.isoformat(),
                "last_activity_at": r.last_activity_at.isoformat(),
                "expires_at": r.expires_at.isoformat(),
                "device_label": r.device_label,
                "network_context": r.network_prefix,
                "current": r.id == identity.auth_session.id,
            }
            for r in rows
        ]
    }


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: str,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    try:
        from uuid import UUID

        sid = UUID(session_id)
    except ValueError as exc:
        raise DomainError("invalid_session_id", "Identifikátor relace není platný.", 422) from exc
    row = await session.get(AuthSession, sid)
    if row is None or row.account_id != identity.account.id:
        return
    await request.app.state.identity.revoke_session(
        session, row, "administrator_revoked", identity.audit_context
    )


@router.post("/password/change")
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    if payload.new_password.get_secret_value() != payload.confirmation.get_secret_value():
        raise DomainError("password_confirmation", "Potvrzení nového hesla se neshoduje.", 422)
    await request.app.state.identity.change_password(
        session,
        identity.account,
        payload.current_password.get_secret_value(),
        payload.new_password.get_secret_value(),
        identity.audit_context,
    )
    return {"changed": True, "other_sessions_revoked": True}


@router.post("/password/forgot", status_code=202)
async def forgot_password(
    payload: PasswordResetRequest, request: Request, session: AsyncSession = Depends(db_session)
):
    account = await session.scalar(
        select(AdministratorAccount).where(AdministratorAccount.username == "Karmar78")
    )
    if account and payload.username == "Karmar78":
        await request.app.state.jobs.enqueue(
            session,
            "password_reset_notification",
            {"account_id": str(account.id)},
            correlation_id=request.state.correlation_id,
        )
    return {
        "accepted": True,
        "message": "Pokud je bezpečná e-mailová obnova připravena, budou odeslány další pokyny.",
    }


@router.post("/password/reset")
async def reset_password(
    payload: PasswordResetComplete, request: Request, session: AsyncSession = Depends(db_session)
):
    if payload.new_password.get_secret_value() != payload.confirmation.get_secret_value():
        raise DomainError("password_confirmation", "Potvrzení nového hesla se neshoduje.", 422)
    context = AuditContext(
        "recovery",
        network_context=network_context(request),
        correlation_id=request.state.correlation_id,
    )
    await request.app.state.identity.complete_reset(
        session, payload.token.get_secret_value(), payload.new_password.get_secret_value(), context
    )
    return {"reset": True, "login_required": True}
