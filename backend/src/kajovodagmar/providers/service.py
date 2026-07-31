from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.audit.service import AuditContext, AuditService
from kajovodagmar.config import get_settings
from kajovodagmar.db.models import EncryptedSecret, ModelCatalogEntry, ProviderConfiguration
from kajovodagmar.errors import (
    CapabilityUnavailableError,
    ConflictError,
    DomainError,
    NotFoundError,
)
from kajovodagmar.providers.deterministic import DeterministicProvider
from kajovodagmar.providers.model_roles import classify_model
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
        old_secret_id = row.secret_id if row else None
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
            if old_secret_id:
                old_secret = await session.get(EncryptedSecret, old_secret_id, with_for_update=True)
                if old_secret is not None:
                    old_secret.revoked_at = utc_now()
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
        try:
            models = await provider.list_models()
        except Exception:
            row.catalog_state = "stale_error"
            await self.audit.append(
                session,
                context=context,
                event_type="provider.verification_failed",
                result="failure",
                target_id=row.id,
                details={"reason": "catalog_refresh_failed"},
            )
            raise
        if not models:
            row.catalog_state = "empty"
            await self.audit.append(
                session,
                context=context,
                event_type="provider.verification_failed",
                result="failure",
                target_id=row.id,
                details={"reason": "empty_catalog"},
            )
            raise DomainError(
                "empty_model_catalog", "Poskytovatel vrátil prázdnou nabídku modelů.", 503
            )
        row.verification_state = "verified"
        row.verified_at = utc_now()
        row.enabled = True
        row.catalog_refreshed_at = utc_now()
        row.catalog_state = "ready"
        previous = []
        if hasattr(session, "scalars"):
            previous = list(
                (
                    await session.scalars(
                        select(ModelCatalogEntry).where(ModelCatalogEntry.provider_id == row.id)
                    )
                ).all()
            )
        for existing in previous:
            existing.available = False
        catalog: list[ModelCatalogEntry] = []
        for model in models:
            classified = classify_model(model.external_id, model.display_name, model.capabilities)
            for role in sorted(classified.roles):
                entry: ModelCatalogEntry | None = await session.scalar(
                    select(ModelCatalogEntry).where(
                        ModelCatalogEntry.provider_id == row.id,
                        ModelCatalogEntry.external_id == model.external_id,
                        ModelCatalogEntry.role == role,
                    )
                )
                if entry is None:
                    entry = ModelCatalogEntry(
                        provider_id=row.id,
                        external_id=model.external_id,
                        display_name=model.display_name,
                        role=role,
                        capabilities=classified.capabilities,
                        available=True,
                    )
                    session.add(entry)
                else:
                    entry.display_name = model.display_name
                    entry.capabilities = classified.capabilities
                    entry.available = True
                    entry.last_seen_at = utc_now()
                catalog.append(entry)
        await self.audit.append(
            session,
            context=context,
            event_type="provider.verified",
            result="success",
            target_id=row.id,
            details={"model_count": len(models), "role_option_count": len(catalog)},
        )
        return catalog

    async def runtime(
        self, session: AsyncSession, row: ProviderConfiguration
    ) -> OpenAICompatibleProvider | DeterministicProvider:
        if row.provider_type == "deterministic":
            if get_settings().environment != "test":
                raise CapabilityUnavailableError(
                    "provider", "Deterministický provider je povolen pouze v testovacím prostředí."
                )
            return DeterministicProvider()
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
