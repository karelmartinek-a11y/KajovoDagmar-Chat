from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from kajovodagmar.config import InfrastructureSettings
from kajovodagmar.observability.tracing import span


class Database:
    def __init__(self, settings: InfrastructureSettings) -> None:
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_recycle=1800,
            connect_args={"server_settings": {"application_name": "kajovodagmar-web"}},
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, autoflush=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        with span("database.transaction", **{"db.system": "postgresql"}):
            async with self.sessions() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

    async def dispose(self) -> None:
        await self.engine.dispose()
