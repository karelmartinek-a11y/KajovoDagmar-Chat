from __future__ import annotations

import base64

import pytest

from kajovodagmar.security.crypto import (
    EncryptedValue,
    SecretCipher,
    hash_password,
    password_policy_errors,
    token_digest,
    verify_password,
)


def test_password_policy_accepts_long_passphrase() -> None:
    assert password_policy_errors("správce hesel vytvořil dlouhou větu 2026") == []


@pytest.mark.parametrize("password", ["short", "Karmar78", "password123"])
def test_password_policy_rejects_unsafe_values(password: str) -> None:
    assert password_policy_errors(password)


def test_argon2_round_trip_and_wrong_password() -> None:
    stored = hash_password("bezpečná dlouhá přístupová věta 2026")
    assert stored.startswith("$argon2id$")
    assert verify_password(stored, "bezpečná dlouhá přístupová věta 2026")[0]
    assert not verify_password(stored, "jiná nesprávná přístupová věta")[0]


def test_secret_cipher_binds_purpose_and_record() -> None:
    key = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
    cipher = SecretCipher(key)
    encrypted = cipher.encrypt(
        "skutečné tajemství", purpose="provider_api_key", record_id="record-1"
    )
    assert "skutečné tajemství" not in encrypted.to_json()
    assert (
        cipher.decrypt(EncryptedValue.from_json(encrypted.to_json()))
        == "skutečné tajemství"
    )


def test_token_digest_is_purpose_scoped() -> None:
    assert token_digest("abc", "session") != token_digest("abc", "password_reset")
