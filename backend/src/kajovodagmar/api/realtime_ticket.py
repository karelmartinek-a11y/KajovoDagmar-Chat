from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.api.dependencies import RequestIdentity, db_session, realtime_identity
from kajovodagmar.realtime.tickets import issue_ticket
from kajovodagmar.security.voice_service import VoiceServiceIdentity

router = APIRouter(prefix="/realtime", tags=["realtime"])


@router.post("/ticket")
async def ticket(
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity | VoiceServiceIdentity = Depends(realtime_identity),
):
    account_id = identity.account.id if isinstance(identity, RequestIdentity) else None
    if account_id is None:
        from sqlalchemy import select

        from kajovodagmar.db.models import AdministratorAccount

        account = await session.scalar(
            select(AdministratorAccount).where(AdministratorAccount.username == "Karmar78")
        )
        if account is None:
            raise RuntimeError("Primární účet Karmar78 není inicializován.")
        account_id = account.id
    value, expires = await issue_ticket(session, account_id)
    return {"ticket": value, "expires_at": expires, "websocket_path": "/api/v1/realtime"}
