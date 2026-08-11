from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_PASSWORD_HASHER = PasswordHasher(
    time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16
)

COMMON_COMPROMISED = frozenset(
    {
        "password",
        "password123",
        "12345678901234",
        "qwertyuiopasdf",
        "letmeinletmein",
        "karmar78karmar78",
    }
)


@dataclass(frozen=True, slots=True)
class EncryptedValue:
    key_version: int
    nonce: str
    ciphertext: str
    associated_data: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "key_version": self.key_version,
                "nonce": self.nonce,
                "ciphertext": self.ciphertext,
                "associated_data": self.associated_data,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, value: str) -> EncryptedValue:
        data = json.loads(value)
        return cls(**data)


class SecretCipher:
    def __init__(self, root_key: str, key_version: int = 1) -> None:
        padding = "=" * (-len(root_key) % 4)
        key = base64.urlsafe_b64decode(root_key + padding)
        if len(key) != 32:
            raise ValueError("Kořenový klíč musí dekódovat na přesně 32 bytů.")
        self._aes = AESGCM(key)
        self.key_version = key_version

    def encrypt(self, plaintext: str, *, purpose: str, record_id: str) -> EncryptedValue:
        nonce = secrets.token_bytes(12)
        aad = f"kajovodagmar:{purpose}:{record_id}:v{self.key_version}".encode()
        ciphertext = self._aes.encrypt(nonce, plaintext.encode(), aad)
        return EncryptedValue(
            self.key_version,
            base64.urlsafe_b64encode(nonce).decode(),
            base64.urlsafe_b64encode(ciphertext).decode(),
            base64.urlsafe_b64encode(aad).decode(),
        )

    def decrypt(self, value: EncryptedValue) -> str:
        nonce = base64.urlsafe_b64decode(value.nonce)
        ciphertext = base64.urlsafe_b64decode(value.ciphertext)
        aad = base64.urlsafe_b64decode(value.associated_data)
        return self._aes.decrypt(nonce, ciphertext, aad).decode()


def password_policy_errors(password: str, username: str = "Karmar78") -> list[str]:
    errors: list[str] = []
    if len(password) < 8:
        errors.append("Heslo musí mít alespoň 8 znaků.")
    if len(password) > 128:
        errors.append("Heslo může mít nejvýše 128 znaků.")
    normalized = password.casefold().strip()
    if normalized == username.casefold():
        errors.append("Heslo nesmí být shodné s uživatelským jménem.")
    if normalized in COMMON_COMPROMISED:
        errors.append("Toto heslo je v lokálním seznamu známých kompromitovaných hesel.")
    return errors


def hash_password(password: str) -> str:
    errors = password_policy_errors(password)
    if errors:
        raise ValueError(" ".join(errors))
    return _PASSWORD_HASHER.hash(password)


def verify_password(stored_hash: str, password: str) -> tuple[bool, str | None]:
    try:
        valid = _PASSWORD_HASHER.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False, None
    upgraded = (
        _PASSWORD_HASHER.hash(password)
        if _PASSWORD_HASHER.check_needs_rehash(stored_hash)
        else None
    )
    return valid, upgraded


def generate_token(byte_length: int = 32) -> str:
    return secrets.token_urlsafe(byte_length)


def token_digest(token: str, purpose: str) -> str:
    return hashlib.sha256(f"kajovodagmar:{purpose}:{token}".encode()).hexdigest()


def secure_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())
