from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.audit.service import AuditContext, AuditService
from kajovodagmar.db.models import EncryptedSecret, ModelCatalogEntry, ProviderConfiguration
from kajovodagmar.errors import CapabilityUnavailableError, ConflictError, NotFoundError
from kajovodagmar.providers.openai_compatible import OpenAICompatibleProvider
from kajovodagmar.security.crypto import EncryptedValue, SecretCipher
from kajovodagmar.types import utc_now


class ProviderService:
    def __init__(self, cipher: SecretCipher, audit: AuditService) -> None:
        self.cipher = cipher
        self.audit = audit

    async def save(
        self,
        session: AsyncSession,
        *,
        provider_id: UUID | None,
        provider_type: str,
        display_name: str,
        base_url: str,
        api_key: str | None,
        expected_version: int,
        context: AuditContext,
    ) -> ProviderConfiguration:
        row = (
            await session.get(ProviderConfiguration, provider_id, with_for_update=True)
            if provider_id
            else None
        )
        if row and row.version != expected_version:
            raise ConflictError("Konfigurace poskytovatele byla mezitím změněna.")
        if row is None:
            row = ProviderConfiguration(
                provider_type=provider_type,
                display_name=display_name,
                base_url=base_url,
                enabled=False,
            )
            session.add(row)
            await session.flush()
        else:
            row.provider_type = provider_type
            row.display_name = display_name
            row.base_url = base_url
            row.version += 1
            row.verification_state = "not_verified"
        if api_key:
            encrypted = self.cipher.encrypt(
                api_key, purpose="provider_api_key", record_id=str(row.id)
            )
            secret = EncryptedSecret(
                purpose=f"provider:{row.id}",
                ciphertext=encrypted.to_json(),
                key_version=encrypted.key_version,
                masked_hint=self._mask(api_key),
            )
            session.add(secret)
            await session.flush()
            row.secret_id = secret.id
        await self.audit.append(
            session,
            context=context,
            event_type="provider.configuration_saved",
            result="success",
            target_id=row.id,
            details={"provider_type": provider_type, "secret_replaced": bool(api_key)},
        )
        return row

    async def verify(
        self, session: AsyncSession, provider_id: UUID, context: AuditContext
    ) -> list[ModelCatalogEntry]:
        row = await session.get(ProviderConfiguration, provider_id, with_for_update=True)
        if row is None:
            raise NotFoundError("Poskytovatel nebyl nalezen.")
        provider = await self.runtime(session, row)
        models = await provider.list_models()
        row.verification_state = "verified"
        row.verified_at = utc_now()
        row.enabled = True
        catalog: list[ModelCatalogEntry] = []
        for model in models:
            existing = await session.scalar(
                select(ModelCatalogEntry).where(
                    ModelCatalogEntry.provider_id == row.id,
                    ModelCatalogEntry.external_id == model.external_id,
                    ModelCatalogEntry.role == "unassigned",
                )
            )
            if existing is None:
                existing = ModelCatalogEntry(
                    provider_id=row.id,
                    external_id=model.external_id,
                    display_name=model.display_name,
                    role="unassigned",
                    capabilities={cap: True for cap in model.capabilities},
                    available=True,
                )
                session.add(existing)
            else:
                existing.display_name = model.display_name
                existing.capabilities = {cap: True for cap in model.capabilities}
                existing.available = True
                existing.last_seen_at = utc_now()
            catalog.append(existing)
        await self.audit.append(
            session,
            context=context,
            event_type="provider.verified",
            result="success",
            target_id=row.id,
            details={"model_count": len(catalog)},
        )
        return catalog

    async def runtime(
        self, session: AsyncSession, row: ProviderConfiguration
    ) -> OpenAICompatibleProvider:
        if not row.secret_id:
            raise CapabilityUnavailableError(
                "provider", "Poskytovatel nemá uložený přístupový klíč."
            )
        secret = await session.get(EncryptedSecret, row.secret_id)
        if secret is None or secret.revoked_at:
            raise CapabilityUnavailableError(
                "provider", "Přístupové tajemství poskytovatele není dostupné."
            )
        key = self.cipher.decrypt(EncryptedValue.from_json(secret.ciphertext))
        if row.provider_type not in {"openai", "openai_compatible"}:
            raise CapabilityUnavailableError(
                "provider", "Typ poskytovatele není podporován touto verzí."
            )
        return OpenAICompatibleProvider(row.base_url, key)

    @staticmethod
    def _mask(value: str) -> str:
        return f"••••{value[-4:]}" if len(value) >= 4 else "••••"
