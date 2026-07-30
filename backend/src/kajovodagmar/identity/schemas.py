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
    def fixed_username(cls, value: str) -> str:
        if value != "Karmar78":
            raise ValueError("Povolené uživatelské jméno je pouze Karmar78.")
        return value

    def validate_passwords(self) -> None:
        password = self.password.get_secret_value()
        if password != self.password_confirmation.get_secret_value():
            raise ValueError("Potvrzení hesla se neshoduje.")
        errors = password_policy_errors(password)
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
