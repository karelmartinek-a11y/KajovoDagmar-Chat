from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.db.models import BackgroundJob
from kajovodagmar.types import utc_now


class JobService:
    async def enqueue(
        self,
        session: AsyncSession,
        kind: str,
        payload: dict[str, Any],
        *,
        priority: int = 100,
        delay_seconds: int = 0,
        correlation_id: str | None = None,
        job_id: UUID | None = None,
    ) -> BackgroundJob:
        job = BackgroundJob(
            **({"id": job_id} if job_id is not None else {}),
            kind=kind,
            state="queued",
            payload=payload,
            priority=priority,
            available_at=utc_now() + timedelta(seconds=delay_seconds),
            correlation_id=correlation_id,
        )
        session.add(job)
        await session.flush()
        return job

    async def claim(
        self,
        session: AsyncSession,
        worker_id: str,
        limit: int = 10,
        allowed_kinds: set[str] | frozenset[str] | None = None,
    ) -> list[BackgroundJob]:
        if not allowed_kinds:
            return []
        rows = list(
            (
                await session.scalars(
                    select(BackgroundJob)
                    .where(
                        BackgroundJob.state == "queued",
                        BackgroundJob.available_at <= utc_now(),
                        BackgroundJob.kind.in_(allowed_kinds),
                    )
                    .order_by(BackgroundJob.priority, BackgroundJob.available_at)
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            ).all()
        )
        for row in rows:
            row.state = "running"
            row.locked_at = utc_now()
            row.locked_by = worker_id
            row.attempts += 1
        return rows

    async def complete(self, job: BackgroundJob) -> None:
        job.state = "completed"
        job.completed_at = utc_now()
        job.locked_at = None
        job.locked_by = None

    async def fail(self, job: BackgroundJob, code: str) -> None:
        job.last_error_code = code
        job.locked_at = None
        job.locked_by = None
        if job.attempts >= job.max_attempts:
            job.state = "failed"
        else:
            job.state = "queued"
            job.available_at = utc_now() + timedelta(seconds=min(3600, 2**job.attempts * 10))
