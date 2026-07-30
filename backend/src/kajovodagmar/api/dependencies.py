from __future__ import annotations

from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.audit.service import AuditContext
from kajovodagmar.db.models import AdministratorAccount, AuthSession
from kajovodagmar.errors import UnauthorizedError


@dataclass(slots=True)
class RequestIdentity:
    account: AdministratorAccount
    auth_session: AuthSession
    audit_context: AuditContext


async def db_session(request: Request):
    async with request.app.state.database.session() as session:
        yield session


def network_context(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    if ":" in host:
        parts = host.split(":")
        return ":".join(parts[:4]) + "::/64"
    octets = host.split(".")
    return ".".join(octets[:3]) + ".0/24" if len(octets) == 4 else "unknown"


async def current_identity(
    request: Request,
    session: AsyncSession = Depends(db_session),
    kajovodagmar_session: str | None = Cookie(default=None, alias="__Host-kajovodagmar_session"),
) -> RequestIdentity:
    if not kajovodagmar_session:
        raise UnauthorizedError()
    idle = await request.app.state.setting_value(session, "security", "session_idle_minutes", 30)
    auth_session, account = await request.app.state.identity.resolve_session(
        session, kajovodagmar_session, idle_minutes=int(idle)
    )
    correlation_id = getattr(request.state, "correlation_id", None)
    return RequestIdentity(
        account,
        auth_session,
        AuditContext(
            "administrator", account.id, auth_session.id, network_context(request), correlation_id
        ),
    )


async def csrf_guard(
    identity: RequestIdentity = Depends(current_identity),
    x_csrf_token: str | None = Header(default=None),
) -> RequestIdentity:
    from kajovodagmar.security.crypto import secure_equals, token_digest

    if not x_csrf_token or not secure_equals(
        identity.auth_session.csrf_digest, token_digest(x_csrf_token, "csrf")
    ):
        from kajovodagmar.errors import DomainError

        raise DomainError("csrf_failed", "Bezpečnostní ověření požadavku selhalo.", 403)
    return identity
