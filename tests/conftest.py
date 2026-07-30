from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from kajovodagmar.config import get_settings
from kajovodagmar.main import create_app
from kajovodagmar.security.crypto import token_digest

INITIALIZATION_SECRET = "synthetic-e2e-initialization-secret"


@pytest.fixture(scope="session")
def synthetic_root_key() -> str:
    return base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")


@pytest.fixture
def clean_environment(monkeypatch: pytest.MonkeyPatch, synthetic_root_key: str) -> None:
    monkeypatch.setenv("KAJOVODAGMAR_ENVIRONMENT", "test")
    monkeypatch.setenv("KAJOVODAGMAR_PUBLIC_ORIGIN", "http://localhost:5173")
    monkeypatch.setenv("KAJOVODAGMAR_ROOT_ENCRYPTION_KEY", synthetic_root_key)
    monkeypatch.setenv("KAJOVODAGMAR_INITIALIZATION_SECRET_HASH", "0" * 64)


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    url = os.environ.get("KAJOVODAGMAR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("KAJOVODAGMAR_TEST_DATABASE_URL není nastavena.")
    engine = create_async_engine(url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        transaction = await session.begin()
        try:
            yield session
        finally:
            await transaction.rollback()
    await engine.dispose()


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    database_url = os.environ["KAJOVODAGMAR_TEST_DATABASE_URL"]
    monkeypatch.setenv("KAJOVODAGMAR_DATABASE_URL", database_url)
    monkeypatch.setenv("KAJOVODAGMAR_ENVIRONMENT", "test")
    monkeypatch.setenv("KAJOVODAGMAR_PUBLIC_ORIGIN", "https://testserver")
    monkeypatch.setenv(
        "KAJOVODAGMAR_INITIALIZATION_SECRET_HASH",
        token_digest(INITIALIZATION_SECRET, "initialization"),
    )
    get_settings.cache_clear()
    with TestClient(create_app(), base_url="https://testserver") as client:
        yield client
    get_settings.cache_clear()
