from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.audit.service import AuditContext, AuditService
from kajovodagmar.db.models import (
    ApplicationSetting,
    ApplicationSettingRevision,
    ModelCatalogEntry,
    ProviderConfiguration,
)
from kajovodagmar.errors import DomainError
from kajovodagmar.providers.model_roles import (
    MODEL_RECOMMENDATION_POLICY_VERSION,
    PREFERENCES,
    ROLE_DESCRIPTIONS,
    ROLE_DETAILS,
    ROLE_ORDER,
    ROLE_TITLES,
    recommendation_rank,
)
from kajovodagmar.settings.catalog import BY_KEY


class ModelRecommendationService:
    policy_version = MODEL_RECOMMENDATION_POLICY_VERSION

    def __init__(self, audit: AuditService) -> None:
        self.audit = audit

    async def model_options(self, session: AsyncSession, provider_id: UUID) -> dict[str, Any]:
        provider = await session.get(ProviderConfiguration, provider_id)
        if provider is None:
            raise DomainError("not_found", "Poskytovatel nebyl nalezen.", 404)
        entries = list(
            (
                await session.scalars(
                    select(ModelCatalogEntry).where(
                        ModelCatalogEntry.provider_id == provider_id,
                        ModelCatalogEntry.available.is_(True),
                    )
                )
            ).all()
        )
        roles: dict[str, Any] = {}
        for role in ROLE_ORDER:
            relevant = [entry for entry in entries if entry.role == role]
            relevant.sort(
                key=lambda entry: (recommendation_rank(role, entry.external_id), entry.external_id)
            )
            recommended = relevant[0] if relevant else None
            selected = await session.scalar(
                select(ApplicationSetting).where(
                    ApplicationSetting.area == "models", ApplicationSetting.key == role
                )
            )
            roles[role] = {
                "title": ROLE_TITLES[role],
                "plain_description": ROLE_DESCRIPTIONS[role],
                "more_information": ROLE_DETAILS[role],
                "recommended_model_id": str(recommended.id) if recommended else None,
                "selected_model_id": selected.value.get("value") if selected else None,
                "status": "ready" if relevant else "missing_supported_model",
                "options": [
                    {
                        "id": str(entry.id),
                        "display_name": entry.display_name,
                        "external_id": entry.external_id,
                        "recommended": entry.id == (recommended.id if recommended else None),
                        "recommendation_reason": self.reason(role, entry.external_id),
                    }
                    for entry in relevant
                ],
            }
        return {
            "provider_id": str(provider.id),
            "provider_verified": provider.verification_state == "verified",
            "catalog_refreshed_at": provider.catalog_refreshed_at.isoformat()
            if provider.catalog_refreshed_at
            else None,
            "catalog_state": provider.catalog_state,
            "policy_version": self.policy_version,
            "roles": roles,
        }

    async def apply_recommended(
        self, session: AsyncSession, provider_id: UUID, account_id: UUID, context: AuditContext
    ) -> dict[str, Any]:
        options = await self.model_options(session, provider_id)
        changes: dict[str, str] = {}
        for role, data in options["roles"].items():
            if data["recommended_model_id"] is None:
                continue
            await self._set_setting(session, role, data["recommended_model_id"], account_id)
            changes[role] = data["recommended_model_id"]
        await self.audit.append(
            session,
            context=context,
            event_type="models.recommendations_applied",
            result="success",
            target_type="provider_configuration",
            target_id=provider_id,
            details={"policy_version": self.policy_version, "roles_changed": sorted(changes)},
        )
        return {"policy_version": self.policy_version, "changes": changes, "options": options}

    async def _set_setting(
        self, session: AsyncSession, key: str, value: str, account_id: UUID
    ) -> None:
        definition = BY_KEY["models", key]
        row = await session.scalar(
            select(ApplicationSetting)
            .where(ApplicationSetting.area == "models", ApplicationSetting.key == key)
            .with_for_update()
        )
        if row is None:
            row = ApplicationSetting(
                area="models",
                key=key,
                value={"value": value},
                effect_boundary=definition.effect_boundary,
                changed_by=account_id,
            )
            session.add(row)
            await session.flush()
        else:
            row.value = {"value": value}
            row.version += 1
            row.changed_by = account_id
        session.add(
            ApplicationSettingRevision(
                setting_id=row.id,
                revision_number=row.version,
                value={"value": value},
                effect_boundary=definition.effect_boundary,
                changed_by=account_id,
                change_kind="automatic_recommendation",
            )
        )

    @staticmethod
    def reason(role: str, model_id: str) -> str:
        if model_id == PREFERENCES[role][0]:
            reasons = {
                "conversation_model": "Vyvážená rychlost a kvalita pro živý rozhovor.",
                "transcription_model": "Přesný převod řeči pro běžný hlasový rozhovor.",
                "speech_model": "Přirozená a rychlá hlasová syntéza.",
                "embedding_model": "Nejlepší dostupná přesnost významového hledání.",
                "summary_model": "Rychlý a úsporný model pro názvy a shrnutí.",
            }
            return reasons[role]
        return "Kompatibilní záložní volba podle doporučovací politiky."
