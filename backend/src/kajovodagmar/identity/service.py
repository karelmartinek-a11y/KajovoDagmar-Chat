from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.audit.service import AuditContext, AuditService
from kajovodagmar.db.models import (
    AccountCredential,
    AdministratorAccount,
    AdministratorProfile,
    AuthSession,
    SecurityToken,
    SystemInstance,
)
from kajovodagmar.errors import ConflictError, DomainError, UnauthorizedError
from kajovodagmar.identity.schemas import InitializeRequest
from kajovodagmar.security.crypto import (
    generate_token,
    hash_password,
    password_policy_errors,
    secure_equals,
    token_digest,
    verify_password,
)
from kajovodagmar.security.rate_limit import restriction_until
from kajovodagmar.types import utc_now


@dataclass(frozen=True, slots=True)
class NewSession:
    record: AuthSession
    cookie_value: str
    csrf_value: str


class IdentityService:
    def __init__(self, audit: AuditService) -> None:
        self.audit = audit

    async def initialization_state(self, session: AsyncSession) -> str:
        instance = await session.scalar(
            select(SystemInstance).where(SystemInstance.singleton_key == "primary")
        )
        return instance.state if instance else "uninitialized"

    async def initialize(
        self, session: AsyncSession, request: InitializeRequest, audit_context: AuditContext
    ) -> AdministratorAccount:
        request.validate_passwords()
        instance = await session.scalar(
            select(SystemInstance)
            .where(SystemInstance.singleton_key == "primary")
            .with_for_update()
        )
        if instance is None:
            raise DomainError(
                "instance_not_bootstrapped",
                "Instance nebyla bezpečně připravena provozním bootstrapem.",
                503,
            )
        if (
            instance.state != "uninitialized"
            or instance.initialization_secret_consumed_at is not None
        ):
            raise ConflictError("Inicializace již byla dokončena.")
        presented = token_digest(request.initialization_secret.get_secret_value(), "initialization")
        if not secure_equals(presented, instance.initialization_secret_digest):
            await self.audit.append(
                session,
                context=audit_context,
                event_type="identity.initialization_failed",
                result="denied",
            )
            raise UnauthorizedError("Inicializační údaje nejsou platné.")
        existing = await session.scalar(select(AdministratorAccount).limit(1))
        if existing is not None:
            raise ConflictError("Administrátorský účet již existuje.")
        account = AdministratorAccount(username="Karmar78", state="active")
        session.add(account)
        await session.flush()
        session.add(
            AccountCredential(
                account_id=account.id,
                password_hash=hash_password(request.password.get_secret_value()),
            )
        )
        session.add(
            AdministratorProfile(
                account_id=account.id,
                display_name=request.display_name,
                email=str(request.email) if request.email else None,
                email_state="pending" if request.email else "not_set",
            )
        )
        instance.state = "active"
        instance.initialized_at = utc_now()
        instance.initialization_secret_consumed_at = utc_now()
        await self.audit.append(
            session,
            context=AuditContext(
                "administrator", account.id, correlation_id=audit_context.correlation_id
            ),
            event_type="identity.initialized",
            result="success",
            target_type="administrator_account",
            target_id=account.id,
        )
        return account

    async def authenticate(
        self, session: AsyncSession, username: str, password: str, audit_context: AuditContext
    ) -> AdministratorAccount:
        account = await session.scalar(
            select(AdministratorAccount)
            .where(AdministratorAccount.username == "Karmar78")
            .with_for_update()
        )
        generic = UnauthorizedError(
            "Přihlašovací údaje nejsou platné nebo je přístup dočasně omezen."
        )
        if account is None or username != "Karmar78":
            await self.audit.append(
                session,
                context=audit_context,
                event_type="identity.login_failed",
                result="denied",
                details={"reason": "credentials"},
            )
            raise generic
        now = utc_now()
        if account.restricted_until and account.restricted_until > now:
            await self.audit.append(
                session,
                context=audit_context,
                event_type="identity.login_restricted",
                result="denied",
                target_id=account.id,
            )
            raise generic
        credential = await session.scalar(
            select(AccountCredential).where(AccountCredential.account_id == account.id)
        )
        if credential is None:
            raise DomainError("credential_missing", "Účet nemá platný přihlašovací záznam.", 503)
        valid, upgraded = verify_password(credential.password_hash, password)
        if not valid:
            account.failed_login_count += 1
            account.restricted_until = restriction_until(account.failed_login_count)
            await self.audit.append(
                session,
                context=audit_context,
                event_type="identity.login_failed",
                result="denied",
                target_id=account.id,
                details={"reason": "credentials", "restricted": bool(account.restricted_until)},
            )
            raise generic
        account.failed_login_count = 0
        account.restricted_until = None
        account.last_login_at = now
        if upgraded:
            credential.password_hash = upgraded
            credential.changed_at = now
        await self.audit.append(
            session,
            context=audit_context,
            event_type="identity.login_succeeded",
            result="success",
            target_id=account.id,
        )
        return account

    async def create_session(
        self,
        session: AsyncSession,
        account: AdministratorAccount,
        audit_context: AuditContext,
        idle_minutes: int = 30,
    ) -> NewSession:
        if not 10 <= idle_minutes <= 120:
            raise ValueError("Nečinnost relace musí být 10 až 120 minut.")
        cookie = generate_token(32)
        csrf = generate_token(24)
        now = utc_now()
        record = AuthSession(
            account_id=account.id,
            secret_digest=token_digest(cookie, "session"),
            csrf_digest=token_digest(csrf, "csrf"),
            created_at=now,
            last_activity_at=now,
            expires_at=now + timedelta(minutes=idle_minutes),
            absolute_expires_at=now + timedelta(hours=12),
            network_prefix=audit_context.network_context,
            user_agent_summary=None,
            device_label="Webový prohlížeč",
        )
        session.add(record)
        await session.flush()
        return NewSession(record, cookie, csrf)

    async def resolve_session(
        self, session: AsyncSession, cookie: str, *, touch: bool = True, idle_minutes: int = 30
    ) -> tuple[AuthSession, AdministratorAccount]:
        digest = token_digest(cookie, "session")
        record = await session.scalar(
            select(AuthSession).where(AuthSession.secret_digest == digest).with_for_update()
        )
        now = utc_now()
        if (
            record is None
            or record.revoked_at
            or record.expires_at <= now
            or record.absolute_expires_at <= now
        ):
            raise UnauthorizedError()
        account = await session.get(AdministratorAccount, record.account_id)
        if account is None or account.state != "active":
            raise UnauthorizedError()
        if touch:
            record.last_activity_at = now
            record.expires_at = min(
                now + timedelta(minutes=idle_minutes), record.absolute_expires_at
            )
        return record, account

    async def verify_csrf(self, record: AuthSession, csrf: str | None) -> None:
        if not csrf or not secure_equals(record.csrf_digest, token_digest(csrf, "csrf")):
            raise DomainError("csrf_failed", "Bezpečnostní ověření formuláře selhalo.", 403)

    async def revoke_session(
        self, session: AsyncSession, record: AuthSession, reason: str, context: AuditContext
    ) -> None:
        record.revoked_at = utc_now()
        record.revoke_reason = reason
        await self.audit.append(
            session,
            context=context,
            event_type="identity.session_revoked",
            result="success",
            target_type="auth_session",
            target_id=record.id,
            details={"reason": reason},
        )

    async def change_password(
        self,
        session: AsyncSession,
        account: AdministratorAccount,
        current: str,
        new: str,
        context: AuditContext,
    ) -> str:
        errors = password_policy_errors(new)
        if errors:
            raise DomainError("password_policy", " ".join(errors), 422)
        credential = await session.scalar(
            select(AccountCredential)
            .where(AccountCredential.account_id == account.id)
            .with_for_update()
        )
        if credential is None:
            raise DomainError("credential_missing", "Přihlašovací záznam není dostupný.", 503)
        valid, _ = verify_password(credential.password_hash, current)
        if not valid:
            raise UnauthorizedError("Aktuální heslo není platné.")
        same, _ = verify_password(credential.password_hash, new)
        if same:
            raise DomainError(
                "password_reuse", "Nové heslo nesmí být shodné s aktuálním heslem.", 422
            )
        credential.password_hash = hash_password(new)
        credential.changed_at = utc_now()
        await session.execute(
            update(AuthSession)
            .where(
                AuthSession.account_id == account.id,
                AuthSession.id != context.session_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=utc_now(), revoke_reason="password_changed")
        )
        await self.audit.append(
            session,
            context=context,
            event_type="identity.password_changed",
            result="success",
            target_id=account.id,
        )
        return "changed"

    async def issue_reset_token(self, session: AsyncSession, account: AdministratorAccount) -> str:
        await session.execute(
            update(SecurityToken)
            .where(
                SecurityToken.account_id == account.id,
                SecurityToken.purpose == "password_reset",
                SecurityToken.used_at.is_(None),
                SecurityToken.invalidated_at.is_(None),
            )
            .values(invalidated_at=utc_now())
        )
        token = generate_token(32)
        session.add(
            SecurityToken(
                account_id=account.id,
                purpose="password_reset",
                token_digest=token_digest(token, "password_reset"),
                expires_at=utc_now() + timedelta(minutes=30),
            )
        )
        return token

    async def complete_reset(
        self, session: AsyncSession, token: str, new_password: str, context: AuditContext
    ) -> None:
        errors = password_policy_errors(new_password)
        if errors:
            raise DomainError("password_policy", " ".join(errors), 422)
        digest = token_digest(token, "password_reset")
        record = await session.scalar(
            select(SecurityToken)
            .where(SecurityToken.token_digest == digest, SecurityToken.purpose == "password_reset")
            .with_for_update()
        )
        now = utc_now()
        if record is None or record.used_at or record.invalidated_at or record.expires_at <= now:
            raise DomainError(
                "reset_token_invalid", "Odkaz pro obnovu není platný nebo již vypršel.", 400
            )
        credential = await session.scalar(
            select(AccountCredential)
            .where(AccountCredential.account_id == record.account_id)
            .with_for_update()
        )
        if credential is None:
            raise DomainError("credential_missing", "Přihlašovací záznam není dostupný.", 503)
        credential.password_hash = hash_password(new_password)
        credential.changed_at = now
        record.used_at = now
        await session.execute(
            update(AuthSession)
            .where(AuthSession.account_id == record.account_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason="password_reset")
        )
        await self.audit.append(
            session,
            context=context,
            event_type="identity.password_reset",
            result="success",
            target_id=record.account_id,
        )

    async def verify_current_password(
        self, session: AsyncSession, account: AdministratorAccount, password: str
    ) -> None:
        credential = await session.scalar(
            select(AccountCredential).where(AccountCredential.account_id == account.id)
        )
        if credential is None:
            raise DomainError("credential_missing", "Přihlašovací záznam není dostupný.", 503)
        valid, _ = verify_password(credential.password_hash, password)
        if not valid:
            raise UnauthorizedError("Aktuální heslo není platné.")

    async def begin_email_change(
        self,
        session: AsyncSession,
        account: AdministratorAccount,
        email: str,
        current_password: str,
        context: AuditContext,
    ) -> str:
        await self.verify_current_password(session, account, current_password)
        profile = await session.scalar(
            select(AdministratorProfile)
            .where(AdministratorProfile.account_id == account.id)
            .with_for_update()
        )
        if profile is None:
            raise DomainError("profile_missing", "Profil administrátora není dostupný.", 503)
        normalized = email.strip().casefold()
        if (
            profile.email
            and normalized == profile.email.casefold()
            and profile.email_state == "verified"
        ):
            raise ConflictError("Tato e-mailová adresa je již ověřena.")
        await session.execute(
            update(SecurityToken)
            .where(
                SecurityToken.account_id == account.id,
                SecurityToken.purpose == "email_verify",
                SecurityToken.used_at.is_(None),
                SecurityToken.invalidated_at.is_(None),
            )
            .values(invalidated_at=utc_now())
        )
        token = generate_token(32)
        profile.pending_email = normalized
        profile.email_state = "pending"
        profile.version += 1
        session.add(
            SecurityToken(
                account_id=account.id,
                purpose="email_verify",
                token_digest=token_digest(token, "email_verify"),
                target_digest=hashlib.sha256(normalized.encode()).hexdigest(),
                expires_at=utc_now() + timedelta(minutes=30),
            )
        )
        await self.audit.append(
            session,
            context=context,
            event_type="identity.email_change_started",
            result="success",
            target_id=account.id,
            details={"profile_version": profile.version},
        )
        return token

    async def complete_email_verification(
        self, session: AsyncSession, token: str, context: AuditContext
    ) -> AdministratorProfile:
        record = await session.scalar(
            select(SecurityToken)
            .where(
                SecurityToken.token_digest == token_digest(token, "email_verify"),
                SecurityToken.purpose == "email_verify",
            )
            .with_for_update()
        )
        now = utc_now()
        if record is None or record.used_at or record.invalidated_at or record.expires_at <= now:
            raise DomainError(
                "email_token_invalid", "Ověřovací odkaz není platný nebo již vypršel.", 400
            )
        profile = await session.scalar(
            select(AdministratorProfile)
            .where(AdministratorProfile.account_id == record.account_id)
            .with_for_update()
        )
        if profile is None or not profile.pending_email:
            raise DomainError(
                "email_change_missing", "Čekající změna e-mailu nebyla nalezena.", 400
            )
        digest = hashlib.sha256(profile.pending_email.casefold().encode()).hexdigest()
        if not record.target_digest or not secure_equals(record.target_digest, digest):
            raise DomainError(
                "email_target_mismatch", "Ověřovací odkaz neodpovídá čekající adrese.", 400
            )
        profile.email = profile.pending_email
        profile.pending_email = None
        profile.email_state = "verified"
        profile.email_verified_at = now
        profile.version += 1
        record.used_at = now
        await self.audit.append(
            session,
            context=context,
            event_type="identity.email_verified",
            result="success",
            target_id=record.account_id,
        )
        return profile
