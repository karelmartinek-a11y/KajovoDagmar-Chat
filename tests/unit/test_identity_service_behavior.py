from __future__ import annotations

import hashlib
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr

from kajovodagmar.audit.service import AuditContext
from kajovodagmar.errors import ConflictError, DomainError, UnauthorizedError
from kajovodagmar.identity.schemas import InitializeRequest
from kajovodagmar.identity.service import IdentityService
from kajovodagmar.security.crypto import token_digest, verify_password
from kajovodagmar.types import utc_now


class Session:
    def __init__(
        self,
        *,
        scalar_values: list[Any] | None = None,
        get_values: list[Any] | None = None,
    ) -> None:
        self.scalar_values = scalar_values or []
        self.get_values = get_values or []
        self.added: list[Any] = []
        self.executed = 0

    async def scalar(self, _query: Any) -> Any:
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def get(self, *_args: Any, **_kwargs: Any) -> Any:
        return self.get_values.pop(0) if self.get_values else None

    async def execute(self, _query: Any) -> None:
        self.executed += 1

    def add(self, value: Any) -> None:
        self.added.append(value)
        if getattr(value, "id", None) is None:
            value.id = uuid4()

    async def flush(self) -> None:
        return None


def service() -> Any:
    return IdentityService(cast(Any, SimpleNamespace(append=AsyncMock())))


def context(account_id: Any = None) -> AuditContext:
    return AuditContext(
        "administrator" if account_id else "anonymous",
        account_id,
        session_id=uuid4() if account_id else None,
        correlation_id="identity-test",
    )


def test_initialization_schema_rejects_identity_and_password_policy_violations() -> (
    None
):
    with pytest.raises(ValueError):
        InitializeRequest(
            username="jiný",
            initialization_secret=SecretStr("bootstrap-secret"),
            password=SecretStr("A-very-secure-password-2026"),
            password_confirmation=SecretStr("A-very-secure-password-2026"),
            display_name="Karel",
        )
    mismatch = InitializeRequest(
        initialization_secret=SecretStr("bootstrap-secret"),
        password=SecretStr("A-very-secure-password-2026"),
        password_confirmation=SecretStr("jiné"),
        display_name="Karel",
    )
    with pytest.raises(ValueError, match="Potvrzení"):
        mismatch.validate_passwords()
    weak = InitializeRequest(
        initialization_secret=SecretStr("bootstrap-secret"),
        password=SecretStr("slabé"),
        password_confirmation=SecretStr("slabé"),
        display_name="Karel",
    )
    with pytest.raises(ValueError):
        weak.validate_passwords()


@pytest.mark.asyncio
async def test_initialization_state_and_all_guard_conditions() -> None:
    identity = service()
    assert await identity.initialization_state(cast(Any, Session())) == "uninitialized"
    assert (
        await identity.initialization_state(
            cast(Any, Session(scalar_values=[SimpleNamespace(state="active")]))
        )
        == "active"
    )
    request = InitializeRequest(
        initialization_secret=SecretStr("bootstrap-secret"),
        password=SecretStr("A-very-secure-password-2026"),
        password_confirmation=SecretStr("A-very-secure-password-2026"),
        display_name="Karel",
    )
    with pytest.raises(DomainError, match="bootstrapem"):
        await identity.initialize(cast(Any, Session()), request, context())
    active = SimpleNamespace(
        state="active",
        initialization_secret_consumed_at=utc_now(),
        initialization_secret_digest="",
    )
    with pytest.raises(ConflictError):
        await identity.initialize(
            cast(Any, Session(scalar_values=[active])), request, context()
        )
    uninitialized = SimpleNamespace(
        state="uninitialized",
        initialization_secret_consumed_at=None,
        initialization_secret_digest="wrong",
        initialized_at=None,
    )
    with pytest.raises(UnauthorizedError):
        await identity.initialize(
            cast(Any, Session(scalar_values=[uninitialized])), request, context()
        )
    uninitialized.initialization_secret_digest = token_digest(
        "bootstrap-secret", "initialization"
    )
    with pytest.raises(ConflictError, match="účet již existuje"):
        await identity.initialize(
            cast(
                Any,
                Session(scalar_values=[uninitialized, SimpleNamespace(id=uuid4())]),
            ),
            request,
            context(),
        )
    successful = Session(scalar_values=[uninitialized, None])
    account = await identity.initialize(cast(Any, successful), request, context())
    assert account.username == "Karmar78"
    assert uninitialized.state == "active"
    assert len(successful.added) == 3


@pytest.mark.asyncio
async def test_authentication_restriction_failure_upgrade_and_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = service()
    with pytest.raises(UnauthorizedError):
        await identity.authenticate(
            cast(Any, Session(scalar_values=[None])),
            "Karmar78",
            "password",
            context(),
        )
    account = SimpleNamespace(
        id=uuid4(),
        state="active",
        restricted_until=utc_now() + timedelta(minutes=1),
        failed_login_count=2,
        last_login_at=None,
    )
    with pytest.raises(UnauthorizedError):
        await identity.authenticate(
            cast(Any, Session(scalar_values=[account])),
            "Karmar78",
            "password",
            context(),
        )
    account.restricted_until = None
    with pytest.raises(DomainError, match="přihlašovací záznam"):
        await identity.authenticate(
            cast(Any, Session(scalar_values=[account, None])),
            "Karmar78",
            "password",
            context(),
        )
    credential = SimpleNamespace(password_hash="hash", changed_at=None)
    monkeypatch.setattr(
        "kajovodagmar.identity.service.verify_password",
        lambda *_args: (False, None),
    )
    with pytest.raises(UnauthorizedError):
        await identity.authenticate(
            cast(Any, Session(scalar_values=[account, credential])),
            "Karmar78",
            "wrong",
            context(),
        )
    assert account.failed_login_count == 3
    monkeypatch.setattr(
        "kajovodagmar.identity.service.verify_password",
        lambda *_args: (True, "upgraded"),
    )
    authenticated = await identity.authenticate(
        cast(Any, Session(scalar_values=[account, credential])),
        "Karmar78",
        "right",
        context(),
    )
    assert authenticated is account
    assert account.failed_login_count == 0
    assert credential.password_hash == "upgraded"


@pytest.mark.asyncio
async def test_session_resolution_csrf_revoke_and_bounds() -> None:
    identity = service()
    account = SimpleNamespace(id=uuid4(), state="active")
    with pytest.raises(ValueError):
        await identity.create_session(
            cast(Any, Session()), account, context(account.id), idle_minutes=5
        )
    session = Session()
    created = await identity.create_session(
        cast(Any, session), account, context(account.id), idle_minutes=30
    )
    assert created.record.account_id == account.id
    assert created.cookie_value
    expired = SimpleNamespace(
        revoked_at=None,
        expires_at=utc_now() - timedelta(seconds=1),
        absolute_expires_at=utc_now() + timedelta(hours=1),
    )
    with pytest.raises(UnauthorizedError):
        await identity.resolve_session(
            cast(Any, Session(scalar_values=[expired])), "cookie"
        )
    record = created.record
    with pytest.raises(UnauthorizedError):
        await identity.resolve_session(
            cast(Any, Session(scalar_values=[record], get_values=[None])),
            created.cookie_value,
        )
    resolved, resolved_account = await identity.resolve_session(
        cast(Any, Session(scalar_values=[record], get_values=[account])),
        created.cookie_value,
        touch=False,
    )
    assert resolved is record
    assert resolved_account is account
    with pytest.raises(DomainError, match="formuláře"):
        await identity.verify_csrf(record, "wrong")
    await identity.verify_csrf(record, created.csrf_value)
    await identity.revoke_session(
        cast(Any, Session()), record, "logout", context(account.id)
    )
    assert record.revoke_reason == "logout"


@pytest.mark.asyncio
async def test_password_change_reset_and_current_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = service()
    account = SimpleNamespace(id=uuid4())
    ctx = context(account.id)
    with pytest.raises(DomainError, match="alespoň 14"):
        await identity.change_password(
            cast(Any, Session()), account, "old", "short", ctx
        )
    with pytest.raises(DomainError, match="není dostupný"):
        await identity.change_password(
            cast(Any, Session(scalar_values=[None])),
            account,
            "old",
            "Brand-new-password-2026",
            ctx,
        )
    credential = SimpleNamespace(password_hash="old-hash", changed_at=None)
    monkeypatch.setattr(
        "kajovodagmar.identity.service.verify_password",
        lambda _hash, password: (password in {"old", "Current-password-2026"}, None),
    )
    with pytest.raises(UnauthorizedError):
        await identity.change_password(
            cast(Any, Session(scalar_values=[credential])),
            account,
            "wrong",
            "Brand-new-password-2026",
            ctx,
        )
    with pytest.raises(DomainError, match="shodné"):
        await identity.change_password(
            cast(Any, Session(scalar_values=[credential])),
            account,
            "Current-password-2026",
            "Current-password-2026",
            ctx,
        )
    monkeypatch.setattr(
        "kajovodagmar.identity.service.verify_password",
        lambda _hash, password: (password == "old", None),
    )
    changed_session = Session(scalar_values=[credential])
    assert (
        await identity.change_password(
            cast(Any, changed_session),
            account,
            "old",
            "Brand-new-password-2026",
            ctx,
        )
        == "changed"
    )
    assert changed_session.executed == 1

    reset_session = Session()
    token = await identity.issue_reset_token(cast(Any, reset_session), account)
    assert token
    assert reset_session.executed == 1
    with pytest.raises(DomainError, match="alespoň 14"):
        await identity.complete_reset(cast(Any, Session()), token, "short", ctx)
    with pytest.raises(DomainError, match="již vypršel"):
        await identity.complete_reset(
            cast(Any, Session(scalar_values=[None])),
            token,
            "Another-secure-password-2026",
            ctx,
        )
    reset_record = SimpleNamespace(
        account_id=account.id,
        used_at=None,
        invalidated_at=None,
        expires_at=utc_now() + timedelta(minutes=5),
    )
    with pytest.raises(DomainError, match="není dostupný"):
        await identity.complete_reset(
            cast(Any, Session(scalar_values=[reset_record, None])),
            token,
            "Another-secure-password-2026",
            ctx,
        )
    reset_credential = SimpleNamespace(password_hash="", changed_at=None)
    complete_session = Session(scalar_values=[reset_record, reset_credential])
    await identity.complete_reset(
        cast(Any, complete_session),
        token,
        "Another-secure-password-2026",
        ctx,
    )
    assert reset_record.used_at is not None
    with pytest.raises(DomainError):
        await identity.verify_current_password(
            cast(Any, Session(scalar_values=[None])), account, "old"
        )
    monkeypatch.setattr(
        "kajovodagmar.identity.service.verify_password",
        lambda *_args: (False, None),
    )
    with pytest.raises(UnauthorizedError):
        await identity.verify_current_password(
            cast(Any, Session(scalar_values=[credential])), account, "wrong"
        )


@pytest.mark.asyncio
async def test_deployment_password_synchronization() -> None:
    identity = service()
    deployment_context = AuditContext(
        "deployment", correlation_id="github-actions-production"
    )
    with pytest.raises(DomainError, match="alespoň 14"):
        await identity.synchronize_deployment_password(
            cast(Any, Session()), "short", deployment_context
        )
    assert not await identity.synchronize_deployment_password(
        cast(Any, Session(scalar_values=[None])),
        "Deployment-password-2026",
        deployment_context,
    )
    account = SimpleNamespace(
        id=uuid4(), failed_login_count=4, restricted_until=utc_now()
    )
    with pytest.raises(DomainError, match="není dostupný"):
        await identity.synchronize_deployment_password(
            cast(Any, Session(scalar_values=[account, None])),
            "Deployment-password-2026",
            deployment_context,
        )
    credential = SimpleNamespace(password_hash="old-hash", changed_at=None)
    synchronized_session = Session(scalar_values=[account, credential])
    assert await identity.synchronize_deployment_password(
        cast(Any, synchronized_session),
        "Deployment-password-2026",
        deployment_context,
    )
    assert verify_password(credential.password_hash, "Deployment-password-2026")[0]
    assert credential.changed_at is not None
    assert account.failed_login_count == 0
    assert account.restricted_until is None
    assert synchronized_session.executed == 1
    identity.audit.append.assert_awaited_once()


@pytest.mark.asyncio
async def test_email_change_and_verification_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = service()
    account = SimpleNamespace(id=uuid4())
    ctx = context(account.id)
    identity.verify_current_password = AsyncMock()
    with pytest.raises(DomainError, match="Profil"):
        await identity.begin_email_change(
            cast(Any, Session(scalar_values=[None])),
            account,
            "new@example.invalid",
            "password",
            ctx,
        )
    profile = SimpleNamespace(
        email="same@example.invalid",
        pending_email=None,
        email_state="verified",
        version=1,
        email_verified_at=None,
    )
    with pytest.raises(ConflictError):
        await identity.begin_email_change(
            cast(Any, Session(scalar_values=[profile])),
            account,
            "same@example.invalid",
            "password",
            ctx,
        )
    session = Session(scalar_values=[profile])
    token = await identity.begin_email_change(
        cast(Any, session),
        account,
        " NEW@Example.Invalid ",
        "password",
        ctx,
    )
    assert profile.pending_email == "new@example.invalid"
    assert profile.email_state == "pending"
    assert session.executed == 1

    with pytest.raises(DomainError, match="již vypršel"):
        await identity.complete_email_verification(
            cast(Any, Session(scalar_values=[None])), token, ctx
        )
    record = SimpleNamespace(
        account_id=account.id,
        used_at=None,
        invalidated_at=None,
        expires_at=utc_now() + timedelta(minutes=5),
        target_digest="wrong",
    )
    with pytest.raises(DomainError, match="Čekající"):
        await identity.complete_email_verification(
            cast(Any, Session(scalar_values=[record, None])), token, ctx
        )
    with pytest.raises(DomainError, match="neodpovídá"):
        await identity.complete_email_verification(
            cast(Any, Session(scalar_values=[record, profile])), token, ctx
        )
    record.target_digest = hashlib.sha256(
        profile.pending_email.casefold().encode()
    ).hexdigest()
    verified = await identity.complete_email_verification(
        cast(Any, Session(scalar_values=[record, profile])), token, ctx
    )
    assert verified.email == "new@example.invalid"
    assert verified.pending_email is None
    assert verified.email_state == "verified"
