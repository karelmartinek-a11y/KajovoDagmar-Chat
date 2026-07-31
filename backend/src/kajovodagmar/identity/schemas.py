from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, SecretStr, field_validator

from kajovodagmar.security.crypto import password_policy_errors


class InitializeRequest(BaseModel):
    username: str = "Karmar78"
    initialization_secret: SecretStr
    password: SecretStr
    password_confirmation: SecretStr
    display_name: str = Field(min_length=1, max_length=160)
    email: EmailStr | None = None

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        normalized = value.strip()
        if (
            not 3 <= len(normalized) <= 64
            or not normalized.replace("-", "").replace("_", "").isalnum()
            or (normalized != "Karmar78" and not normalized.startswith("acceptance-"))
        ):
            raise ValueError("Uživatelské jméno musí mít 3 až 64 bezpečných znaků.")
        return normalized

    def validate_passwords(self) -> None:
        password = self.password.get_secret_value()
        if password != self.password_confirmation.get_secret_value():
            raise ValueError("Potvrzení hesla se neshoduje.")
        errors = password_policy_errors(password, self.username)
        if errors:
            raise ValueError(" ".join(errors))


class LoginRequest(BaseModel):
    username: str = "Karmar78"
    password: SecretStr


class ChangePasswordRequest(BaseModel):
    current_password: SecretStr
    new_password: SecretStr
    confirmation: SecretStr


class PasswordResetRequest(BaseModel):
    username: str = "Karmar78"


class PasswordResetComplete(BaseModel):
    token: SecretStr
    new_password: SecretStr
    confirmation: SecretStr


class EmailChangeRequest(BaseModel):
    email: EmailStr
    current_password: SecretStr


class SessionView(BaseModel):
    id: str
    created_at: datetime
    last_activity_at: datetime
    device_label: str | None
    current: bool
