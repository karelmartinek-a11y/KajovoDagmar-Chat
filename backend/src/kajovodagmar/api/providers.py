from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.api.dependencies import RequestIdentity, csrf_guard, current_identity, db_session
from kajovodagmar.db.models import EncryptedSecret, ModelCatalogEntry, ProviderConfiguration

router = APIRouter(prefix="/providers", tags=["providers"])


class ProviderSave(BaseModel):
    id: UUID | None = None
    expected_version: int = Field(default=0, ge=0)
    provider_type: str = Field(pattern="^(openai|openai_compatible)$")
    display_name: str = Field(min_length=1, max_length=160)
    base_url: str = Field(min_length=8, max_length=512)
    api_key: SecretStr | None = None


@router.get("")
async def list_providers(
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    rows = (
        await session.scalars(
            select(ProviderConfiguration).order_by(ProviderConfiguration.display_name)
        )
    ).all()
    items = []
    for r in rows:
        secret = await session.get(EncryptedSecret, r.secret_id) if r.secret_id else None
        models = (
            await session.scalars(
                select(ModelCatalogEntry)
                .where(ModelCatalogEntry.provider_id == r.id)
                .order_by(ModelCatalogEntry.display_name)
            )
        ).all()
        items.append(
            {
                "id": str(r.id),
                "provider_type": r.provider_type,
                "display_name": r.display_name,
                "base_url": r.base_url,
                "enabled": r.enabled,
                "verification_state": r.verification_state,
                "verified_at": r.verified_at.isoformat() if r.verified_at else None,
                "secret_present": bool(secret and not secret.revoked_at),
                "secret_hint": secret.masked_hint if secret else None,
                "version": r.version,
                "catalog_refreshed_at": r.catalog_refreshed_at.isoformat()
                if r.catalog_refreshed_at
                else None,
                "catalog_state": r.catalog_state,
                "models": [
                    {
                        "id": str(m.id),
                        "external_id": m.external_id,
                        "display_name": m.display_name,
                        "role": m.role,
                        "capabilities": m.capabilities,
                        "available": m.available,
                    }
                    for m in models
                ],
            }
        )
    return {"items": items}


@router.put("")
async def save(
    payload: ProviderSave,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    row = await request.app.state.providers.save(
        session,
        provider_id=payload.id,
        provider_type=payload.provider_type,
        display_name=payload.display_name,
        base_url=payload.base_url,
        api_key=payload.api_key.get_secret_value() if payload.api_key else None,
        expected_version=payload.expected_version,
        context=identity.audit_context,
    )
    catalog = await request.app.state.providers.verify(session, row.id, identity.audit_context)
    return {
        "id": str(row.id),
        "version": row.version,
        "verification_state": row.verification_state,
        "catalog_count": len(catalog),
        "recommendations": None,
    }


@router.post("/{provider_id}/verify")
async def verify(
    provider_id: UUID,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    rows = await request.app.state.providers.verify(session, provider_id, identity.audit_context)
    return {
        "verified": True,
        "models": [
            {
                "id": str(r.id),
                "external_id": r.external_id,
                "display_name": r.display_name,
                "capabilities": r.capabilities,
            }
            for r in rows
        ],
        "recommendations": None,
    }


@router.get("/{provider_id}/model-options")
async def model_options(
    provider_id: UUID,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    return await request.app.state.model_recommendations.model_options(session, provider_id)


@router.post("/{provider_id}/apply-recommended-models")
async def apply_recommended(
    provider_id: UUID,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    return await request.app.state.model_recommendations.apply_recommended(
        session, provider_id, identity.account.id, identity.audit_context
    )
