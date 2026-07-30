from __future__ import annotations

import re
from pathlib import Path
import pytest

from kajovodagmar.security.crypto import hash_password, token_digest

pytestmark = pytest.mark.security


def test_password_hash_never_contains_plaintext() -> None:
    password = "unikátní bezpečná věta pro test"
    stored = hash_password(password)
    assert password not in stored
    assert stored.startswith("$argon2id$")


def test_session_cookie_flags_are_source_enforced() -> None:
    source = Path("backend/src/kajovodagmar/api/auth.py").read_text(encoding="utf-8")
    assert "httponly=True" in source
    assert 'samesite="strict"' in source
    assert '"__Host-kajovodagmar_session"' in source


def test_no_auth_token_storage_in_frontend() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("web/src").rglob("*.ts*")
    )
    assert not re.search(
        r"(?:localStorage|sessionStorage)\.setItem\([^\n]*(?:session|access_token|refresh_token)",
        source,
        re.I,
    )
    assert token_digest("same", "session") != token_digest("same", "csrf")
