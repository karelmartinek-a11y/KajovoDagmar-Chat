from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.api.dependencies import RequestIdentity, csrf_guard, db_session
from kajovodagmar.realtime.tickets import issue_ticket

router = APIRouter(prefix="/realtime", tags=["realtime"])


@router.post("/ticket")
async def ticket(
    session: AsyncSession = Depends(db_session), identity: RequestIdentity = Depends(csrf_guard)
):
    value, expires = await issue_ticket(session, identity.account.id)
    return {"ticket": value, "expires_at": expires, "websocket_path": "/api/v1/realtime"}
