from __future__ import annotations

import hashlib
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.audit.service import AuditContext, AuditService
from kajovodagmar.db.models import (
    AdministratorAccount,
    AdministratorProfile,
    EncryptedSecret,
    NotificationDelivery,
    ProviderConfiguration,
)
from kajovodagmar.errors import CapabilityUnavailableError, DomainError
from kajovodagmar.identity.service import IdentityService
from kajovodagmar.notifications.smtp import SMTPConfiguration, SMTPMailer
from kajovodagmar.security.crypto import EncryptedValue, SecretCipher


class NotificationService:
    def __init__(
        self,
        cipher: SecretCipher,
        audit: AuditService,
        identity: IdentityService,
        public_origin: str,
    ) -> None:
        self.cipher = cipher
        self.audit = audit
        self.identity = identity
        self.public_origin = public_origin.rstrip("/")

    async def save_smtp(
        self,
        session: AsyncSession,
        *,
        display_name: str,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        sender: str,
        use_starttls: bool,
        context: AuditContext,
    ) -> ProviderConfiguration:
        if not 1 <= port <= 65535:
            raise DomainError("smtp_port_invalid", "Port SMTP není platný.", 422)
        row = await session.scalar(
            select(ProviderConfiguration)
            .where(ProviderConfiguration.provider_type == "smtp")
            .with_for_update()
        )
        if row is None:
            row = ProviderConfiguration(
                provider_type="smtp",
                display_name=display_name,
                base_url=f"smtp://{host}:{port}",
                enabled=False,
                verification_state="not_verified",
                capabilities={},
            )
            session.add(row)
            await session.flush()
        else:
            row.display_name = display_name
            row.base_url = f"smtp://{host}:{port}"
            row.version += 1
            row.enabled = False
            row.verification_state = "not_verified"
        row.capabilities = {"username": username, "sender": sender, "use_starttls": use_starttls}
        if password:
            encrypted = self.cipher.encrypt(
                password, purpose="smtp_password", record_id=str(row.id)
            )
            secret = EncryptedSecret(
                purpose=f"smtp:{row.id}",
                ciphertext=encrypted.to_json(),
                key_version=encrypted.key_version,
                masked_hint=f"••••{password[-4:] if len(password) >= 4 else ''}",
            )
            session.add(secret)
            await session.flush()
            row.secret_id = secret.id
        await self.audit.append(
            session,
            context=context,
            event_type="notifications.smtp_saved",
            result="success",
            target_id=row.id,
            details={"host": host, "port": port, "password_replaced": bool(password)},
        )
        return row

    async def test_smtp(self, session: AsyncSession, recipient: str, context: AuditContext) -> None:
        row, mailer = await self._mailer(session)
        await mailer.send(
            recipient,
            "KájovoDagmar – test e-mailu",
            "Toto je bezpečný test doručování z aplikace KájovoDagmar.",
        )
        row.enabled = True
        row.verification_state = "verified"
        from kajovodagmar.types import utc_now

        row.verified_at = utc_now()
        await self.audit.append(
            session,
            context=context,
            event_type="notifications.smtp_verified",
            result="success",
            target_id=row.id,
        )

    async def process_password_reset(self, session: AsyncSession, payload: dict[str, str]) -> None:
        account = await session.get(
            AdministratorAccount, UUID(payload["account_id"]), with_for_update=True
        )
        if account is None:
            return
        profile = await session.scalar(
            select(AdministratorProfile).where(AdministratorProfile.account_id == account.id)
        )
        if profile is None or profile.email_state != "verified" or not profile.email:
            raise CapabilityUnavailableError("password_recovery", "Účet nemá ověřený e-mail.")
        _, mailer = await self._mailer(session)
        token = await self.identity.issue_reset_token(session, account)
        link = f"{self.public_origin}/reset-password?token={token}"
        delivery = NotificationDelivery(
            kind="password_reset",
            recipient_digest=hashlib.sha256(profile.email.casefold().encode()).hexdigest(),
            state="sending",
            template_id="password_reset_v1",
            safe_parameters={"account_id": str(account.id)},
        )
        session.add(delivery)
        await session.flush()
        try:
            provider_id = await mailer.send(
                profile.email,
                "KájovoDagmar – obnova hesla",
                f"Odkaz je jednorázový a platí 30 minut:\n\n{link}\n\n"
                "Pokud jste o obnovu nežádal, zprávu ignorujte.",
            )
        except Exception:
            from kajovodagmar.types import utc_now

            delivery.state = "failed"
            delivery.failed_at = utc_now()
            delivery.error_code = "smtp_delivery_failed"
            raise
        from kajovodagmar.types import utc_now

        delivery.state = "sent"
        delivery.sent_at = utc_now()
        delivery.provider_message_id = provider_id

    async def _mailer(self, session: AsyncSession) -> tuple[ProviderConfiguration, SMTPMailer]:
        row = await session.scalar(
            select(ProviderConfiguration).where(ProviderConfiguration.provider_type == "smtp")
        )
        if row is None:
            raise CapabilityUnavailableError("email", "Odchozí e-mailová služba není nastavena.")
        parsed = urlparse(row.base_url)
        password = None
        if row.secret_id:
            secret = await session.get(EncryptedSecret, row.secret_id)
            if secret and not secret.revoked_at:
                password = self.cipher.decrypt(EncryptedValue.from_json(secret.ciphertext))
        cfg = SMTPConfiguration(
            host=parsed.hostname or "",
            port=parsed.port or 587,
            username=row.capabilities.get("username"),
            password=password,
            sender=row.capabilities.get("sender", ""),
            use_starttls=bool(row.capabilities.get("use_starttls", True)),
        )
        if not cfg.host or not cfg.sender:
            raise CapabilityUnavailableError("email", "Konfigurace odchozí pošty není úplná.")
        return row, SMTPMailer(cfg)

    async def send_email_verification(
        self, session: AsyncSession, recipient: str, token: str
    ) -> None:
        _, mailer = await self._mailer(session)
        link = f"{self.public_origin}/verify-email?token={token}"
        delivery = NotificationDelivery(
            kind="email_verification",
            recipient_digest=hashlib.sha256(recipient.casefold().encode()).hexdigest(),
            state="sending",
            template_id="email_verification_v1",
            safe_parameters={},
        )
        session.add(delivery)
        await session.flush()
        try:
            provider_id = await mailer.send(
                recipient,
                "KájovoDagmar – ověření e-mailu",
                f"Potvrďte novou e-mailovou adresu do 30 minut:\n\n{link}\n\n"
                "Pokud jste změnu nevyžádal, zprávu ignorujte.",
            )
        except Exception:
            from kajovodagmar.types import utc_now

            delivery.state = "failed"
            delivery.failed_at = utc_now()
            delivery.error_code = "smtp_delivery_failed"
            raise
        from kajovodagmar.types import utc_now

        delivery.state = "sent"
        delivery.sent_at = utc_now()
        delivery.provider_message_id = provider_id
