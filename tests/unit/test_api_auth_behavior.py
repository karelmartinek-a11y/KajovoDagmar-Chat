from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr

from kajovodagmar.api.auth import initialize
from kajovodagmar.identity.schemas import InitializeRequest


@pytest.mark.asyncio
async def test_initialize_commits_before_returning_success() -> None:
    account = SimpleNamespace(id=uuid4(), state="active", username="Karmar78")
    identity = SimpleNamespace(initialize=AsyncMock(return_value=account))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(identity=identity)),
        client=None,
        state=SimpleNamespace(correlation_id="test-correlation"),
    )
    session = SimpleNamespace(commit=AsyncMock())
    payload = InitializeRequest(
        initialization_secret=SecretStr("synthetic-initialization-secret"),
        password=SecretStr("Bezpečné syntetické heslo 2026"),
        password_confirmation=SecretStr("Bezpečné syntetické heslo 2026"),
        display_name="Test správce",
    )

    response = await initialize(payload, cast(Any, request), cast(Any, session))

    assert response == {
        "account_id": str(account.id),
        "state": "active",
        "username": "Karmar78",
    }
    session.commit.assert_awaited_once()
