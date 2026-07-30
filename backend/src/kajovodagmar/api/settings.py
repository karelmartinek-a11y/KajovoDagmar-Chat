from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.api.dependencies import RequestIdentity, csrf_guard, current_identity, db_session

router = APIRouter(prefix="/settings", tags=["settings"])


class AreaUpdate(BaseModel):
    changes: dict[str, dict[str, Any]]


class RestoreSettingRequest(BaseModel):
    revision_number: int = Field(ge=1)
    expected_version: int = Field(ge=1)


@router.get("")
async def all_settings(
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    return await request.app.state.settings_service.effective(session)


@router.put("/{area}")
async def update_area(
    area: str,
    payload: AreaUpdate,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    return await request.app.state.settings_service.update_area(
        session, area, payload.changes, identity.account.id, identity.audit_context
    )


@router.get("/{area}/{key}/history")
async def setting_history(
    area: str,
    key: str,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    rows = await request.app.state.settings_service.history(session, area, key)
    return {
        "items": [
            {
                "revision_number": row.revision_number,
                "value": row.value.get("value"),
                "effect_boundary": row.effect_boundary,
                "change_kind": row.change_kind,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }


@router.post("/{area}/{key}/restore")
async def restore_setting(
    area: str,
    key: str,
    payload: RestoreSettingRequest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    row = await request.app.state.settings_service.restore_revision(
        session,
        area,
        key,
        payload.revision_number,
        payload.expected_version,
        identity.account.id,
        identity.audit_context,
    )
    return {
        "value": row.value.get("value"),
        "version": row.version,
        "effect_boundary": row.effect_boundary,
    }
