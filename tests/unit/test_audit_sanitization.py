from datetime import UTC, datetime

from kajovodagmar.audit.service import AuditService
from kajovodagmar.db.models import AuditEvent


def test_audit_redacts_secrets_and_private_content() -> None:
    result = AuditService._sanitize(
        {
            "password": "secret",
            "api_key_hint": "abcd",
            "content": "private",
            "safe": "ok",
        }
    )
    assert result["password"] == "[redacted]"
    assert result["api_key_hint"] == "[redacted]"
    assert result["content"] == "[redacted]"
    assert result["safe"] == "ok"


def test_audit_chain_detects_tampering() -> None:
    event = AuditEvent(
        id=1,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        actor_type="system",
        event_type="backup.completed",
        result="success",
        details={},
        previous_hash=None,
        event_hash="not-a-valid-hash",
    )

    assert AuditService.verify_chain([]) == (True, None)
    assert AuditService.verify_chain([event]) == (False, 1)
