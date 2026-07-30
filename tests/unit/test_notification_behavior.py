from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from kajovodagmar.audit.service import AuditContext
from kajovodagmar.db.models import EncryptedSecret, ProviderConfiguration
from kajovodagmar.errors import CapabilityUnavailableError, DomainError
from kajovodagmar.notifications.service import NotificationService
from kajovodagmar.notifications.smtp import SMTPConfiguration, SMTPMailer
from kajovodagmar.security.crypto import SecretCipher

ROOT_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"


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

    async def scalar(self, _query: Any) -> Any:
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def get(self, *_args: Any, **_kwargs: Any) -> Any:
        return self.get_values.pop(0) if self.get_values else None

    def add(self, value: Any) -> None:
        self.added.append(value)
        if getattr(value, "id", None) is None:
            value.id = uuid4()

    async def flush(self) -> None:
        return None


def service() -> Any:
    return NotificationService(
        SecretCipher(ROOT_KEY),
        cast(Any, SimpleNamespace(append=AsyncMock())),
        cast(
            Any,
            SimpleNamespace(issue_reset_token=AsyncMock(return_value="reset-token")),
        ),
        "https://app.invalid/",
    )


@pytest.mark.asyncio
async def test_smtp_configuration_save_mailer_and_verification() -> None:
    notifications = service()
    context = AuditContext("administrator", uuid4())
    with pytest.raises(DomainError, match="Port SMTP"):
        await notifications.save_smtp(
            cast(Any, Session()),
            display_name="SMTP",
            host="smtp.invalid",
            port=0,
            username=None,
            password=None,
            sender="sender@example.invalid",
            use_starttls=True,
            context=context,
        )
    session = Session(scalar_values=[None])
    row = await notifications.save_smtp(
        cast(Any, session),
        display_name="SMTP",
        host="smtp.invalid",
        port=587,
        username="user",
        password="smtp-secret",
        sender="sender@example.invalid",
        use_starttls=True,
        context=context,
    )
    assert row.base_url == "smtp://smtp.invalid:587"
    assert row.secret_id is not None
    assert row.capabilities["sender"] == "sender@example.invalid"

    row.version = 1
    updated = await notifications.save_smtp(
        cast(Any, Session(scalar_values=[row])),
        display_name="Updated",
        host="mail.invalid",
        port=2525,
        username=None,
        password=None,
        sender="new@example.invalid",
        use_starttls=False,
        context=context,
    )
    assert updated.version == 2
    assert updated.enabled is False

    with pytest.raises(CapabilityUnavailableError):
        await notifications._mailer(cast(Any, Session(scalar_values=[None])))
    incomplete = ProviderConfiguration(
        id=uuid4(),
        provider_type="smtp",
        display_name="Incomplete",
        base_url="smtp://:587",
        capabilities={},
    )
    with pytest.raises(CapabilityUnavailableError):
        await notifications._mailer(cast(Any, Session(scalar_values=[incomplete])))

    encrypted = notifications.cipher.encrypt(
        "smtp-secret", purpose="smtp_password", record_id=str(row.id)
    )
    secret = EncryptedSecret(
        id=row.secret_id,
        purpose="smtp",
        ciphertext=encrypted.to_json(),
        key_version=1,
        masked_hint="••••cret",
    )
    row.base_url = "smtp://smtp.invalid:587"
    row.capabilities = {
        "username": "user",
        "sender": "sender@example.invalid",
        "use_starttls": True,
    }
    configured_row, mailer = await notifications._mailer(
        cast(Any, Session(scalar_values=[row], get_values=[secret]))
    )
    assert configured_row is row
    assert mailer.config.password == "smtp-secret"

    fake_mailer = SimpleNamespace(send=AsyncMock(return_value="accepted"))
    notifications._mailer = AsyncMock(return_value=(row, fake_mailer))
    await notifications.test_smtp(
        cast(Any, Session()), "recipient@example.invalid", context
    )
    assert row.enabled is True
    assert row.verification_state == "verified"


@pytest.mark.asyncio
async def test_password_reset_and_email_verification_delivery_states() -> None:
    notifications = service()
    account = SimpleNamespace(id=uuid4())
    await notifications.process_password_reset(
        cast(Any, Session(get_values=[None])), {"account_id": str(uuid4())}
    )
    with pytest.raises(CapabilityUnavailableError):
        await notifications.process_password_reset(
            cast(Any, Session(get_values=[account], scalar_values=[None])),
            {"account_id": str(account.id)},
        )

    profile = SimpleNamespace(email_state="verified", email="Owner@Example.Invalid")
    row = SimpleNamespace(id=uuid4())
    mailer = SimpleNamespace(send=AsyncMock(return_value="provider-id"))
    notifications._mailer = AsyncMock(return_value=(row, mailer))
    session = Session(get_values=[account], scalar_values=[profile])
    await notifications.process_password_reset(
        cast(Any, session), {"account_id": str(account.id)}
    )
    delivery = session.added[0]
    assert delivery.state == "sent"
    assert delivery.provider_message_id == "provider-id"
    assert "reset-password?token=reset-token" in mailer.send.await_args.args[2]

    failed_mailer = SimpleNamespace(send=AsyncMock(side_effect=RuntimeError("smtp")))
    notifications._mailer = AsyncMock(return_value=(row, failed_mailer))
    failure_session = Session(get_values=[account], scalar_values=[profile])
    with pytest.raises(RuntimeError, match="smtp"):
        await notifications.process_password_reset(
            cast(Any, failure_session), {"account_id": str(account.id)}
        )
    assert failure_session.added[0].state == "failed"
    assert failure_session.added[0].error_code == "smtp_delivery_failed"

    mailer.send.reset_mock()
    notifications._mailer = AsyncMock(return_value=(row, mailer))
    verification_session = Session()
    await notifications.send_email_verification(
        cast(Any, verification_session), "new@example.invalid", "verify-token"
    )
    verification = verification_session.added[0]
    assert verification.state == "sent"
    assert "verify-email?token=verify-token" in mailer.send.await_args.args[2]

    notifications._mailer = AsyncMock(return_value=(row, failed_mailer))
    failed_verification_session = Session()
    with pytest.raises(RuntimeError):
        await notifications.send_email_verification(
            cast(Any, failed_verification_session),
            "new@example.invalid",
            "verify-token",
        )
    assert failed_verification_session.added[0].state == "failed"


def test_smtp_mailer_sync_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class SMTP:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def __enter__(self) -> SMTP:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def starttls(self, **_kwargs: Any) -> None:
            calls.append("starttls")

        def login(self, username: str, password: str) -> None:
            calls.append(f"login:{username}:{password}")

        def send_message(self, _message: Any) -> dict[str, Any]:
            calls.append("send")
            return {}

    monkeypatch.setattr("smtplib.SMTP", SMTP)
    mailer = SMTPMailer(
        SMTPConfiguration(
            host="smtp.invalid",
            port=587,
            username="user",
            password="secret",
            sender="sender@example.invalid",
        )
    )
    assert mailer._send_sync("to@example.invalid", "Předmět", "Text") == "accepted"
    assert calls == ["starttls", "login:user:secret", "send"]

    class RefusingSMTP(SMTP):
        def send_message(self, _message: Any) -> dict[str, Any]:
            return {"to@example.invalid": (550, b"refused")}

    monkeypatch.setattr("smtplib.SMTP", RefusingSMTP)
    with pytest.raises(RuntimeError, match="odmítl"):
        mailer._send_sync("to@example.invalid", "Předmět", "Text")
