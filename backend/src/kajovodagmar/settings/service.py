from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.audit.service import AuditContext, AuditService
from kajovodagmar.db.models import ApplicationSetting, ApplicationSettingRevision
from kajovodagmar.errors import ConflictError, DomainError, NotFoundError
from kajovodagmar.settings.catalog import BY_KEY, DEFINITIONS, validate_value


class SettingsService:
    def __init__(self, audit: AuditService) -> None:
        self.audit = audit

    async def effective(self, session: AsyncSession) -> dict[str, dict[str, Any]]:
        rows = (await session.scalars(select(ApplicationSetting))).all()
        stored = {(r.area, r.key): r for r in rows}
        result: dict[str, dict[str, Any]] = {}
        for definition in DEFINITIONS:
            row = stored.get((definition.area, definition.key))
            result.setdefault(definition.area, {})[definition.key] = {
                "value": row.value["value"] if row else definition.default,
                "version": row.version if row else 0,
                "label": definition.label,
                "description": definition.description,
                "effect_boundary": definition.effect_boundary,
                "type": definition.value_type,
                "choices": definition.choices,
                "minimum": definition.minimum,
                "maximum": definition.maximum,
            }
        return result

    async def update_area(
        self,
        session: AsyncSession,
        area: str,
        changes: dict[str, dict[str, Any]],
        account_id: UUID,
        context: AuditContext,
    ) -> dict[str, Any]:
        outcomes: dict[str, Any] = {}
        for key, request in changes.items():
            definition = BY_KEY.get((area, key))
            if not definition:
                raise DomainError(
                    "setting_unknown", f"Nastavení {area}.{key} není podporováno.", 422
                )
            value = validate_value(definition, request.get("value"))
            expected = int(request.get("version", 0))
            row = await session.scalar(
                select(ApplicationSetting)
                .where(ApplicationSetting.area == area, ApplicationSetting.key == key)
                .with_for_update()
            )
            actual = row.version if row else 0
            if actual != expected:
                raise ConflictError(
                    "Nastavení bylo mezitím změněno v jiné relaci.",
                    {"key": key, "expected_version": expected, "actual_version": actual},
                )
            if row is None:
                row = ApplicationSetting(
                    area=area,
                    key=key,
                    value={"value": value},
                    effect_boundary=definition.effect_boundary,
                    changed_by=account_id,
                )
                session.add(row)
            else:
                row.value = {"value": value}
                row.version += 1
                row.changed_by = account_id
            await session.flush()
            session.add(
                ApplicationSettingRevision(
                    setting_id=row.id,
                    revision_number=row.version,
                    value={"value": value},
                    effect_boundary=definition.effect_boundary,
                    changed_by=account_id,
                    change_kind="changed",
                )
            )
            outcomes[key] = {
                "value": value,
                "version": row.version,
                "effect_boundary": definition.effect_boundary,
            }
            await self.audit.append(
                session,
                context=context,
                event_type="settings.changed",
                result="success",
                target_type="application_setting",
                target_id=row.id,
                details={"area": area, "key": key, "version": row.version},
            )
        return outcomes

    async def history(
        self, session: AsyncSession, area: str, key: str
    ) -> list[ApplicationSettingRevision]:
        row = await session.scalar(
            select(ApplicationSetting).where(
                ApplicationSetting.area == area, ApplicationSetting.key == key
            )
        )
        if row is None:
            return []
        return list(
            (
                await session.scalars(
                    select(ApplicationSettingRevision)
                    .where(ApplicationSettingRevision.setting_id == row.id)
                    .order_by(ApplicationSettingRevision.revision_number.desc())
                    .limit(100)
                )
            ).all()
        )

    async def restore_revision(
        self,
        session: AsyncSession,
        area: str,
        key: str,
        revision_number: int,
        expected_version: int,
        account_id: UUID,
        context: AuditContext,
    ) -> ApplicationSetting:
        definition = BY_KEY.get((area, key))
        if definition is None:
            raise DomainError("setting_unknown", f"Nastavení {area}.{key} není podporováno.", 422)
        row = await session.scalar(
            select(ApplicationSetting)
            .where(ApplicationSetting.area == area, ApplicationSetting.key == key)
            .with_for_update()
        )
        if row is None:
            raise NotFoundError("Nastavení dosud nemá uloženou historii.")
        if row.version != expected_version:
            raise ConflictError(
                "Nastavení bylo mezitím změněno.",
                {"expected_version": expected_version, "actual_version": row.version},
            )
        revision = await session.scalar(
            select(ApplicationSettingRevision).where(
                ApplicationSettingRevision.setting_id == row.id,
                ApplicationSettingRevision.revision_number == revision_number,
            )
        )
        if revision is None:
            raise NotFoundError("Požadovaná verze nastavení nebyla nalezena.")
        value = validate_value(definition, revision.value.get("value"))
        row.value = {"value": value}
        row.effect_boundary = definition.effect_boundary
        row.changed_by = account_id
        row.version += 1
        session.add(
            ApplicationSettingRevision(
                setting_id=row.id,
                revision_number=row.version,
                value=row.value,
                effect_boundary=row.effect_boundary,
                changed_by=account_id,
                change_kind="restored",
            )
        )
        await self.audit.append(
            session,
            context=context,
            event_type="settings.restored",
            result="success",
            target_type="application_setting",
            target_id=row.id,
            details={
                "area": area,
                "key": key,
                "from_revision": revision_number,
                "version": row.version,
            },
        )
        return row
