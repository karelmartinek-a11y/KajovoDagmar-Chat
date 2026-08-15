from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, Query, Request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from kajovodagmar.api.dependencies import (
    RequestIdentity,
    csrf_guard,
    current_identity,
    db_session,
)
from kajovodagmar.audit.service import AuditService
from kajovodagmar.db.models import (
    ApplicationSetting,
    AuditEvent,
    BackgroundJob,
    BackupRecord,
    ModelCatalogEntry,
    ProviderConfiguration,
    SystemInstance,
    WorkerHeartbeat,
)
from kajovodagmar.errors import ConflictError, NotFoundError
from kajovodagmar.observability.metrics import BACKUPS
from kajovodagmar.types import utc_now

router = APIRouter(tags=["operations"])


class BackupRequest(BaseModel):
    purpose: str = Field(min_length=3, max_length=160)
    idempotency_key: str = Field(min_length=16, max_length=128)


class BackupActionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=16, max_length=128)


class RestoreTestRequest(BackupActionRequest):
    confirmation: Literal["OBNOVIT DO IZOLOVANÉHO PROSTŘEDÍ"]


def audit_view(row: AuditEvent) -> dict[str, object]:
    return {
        "id": row.id,
        "occurred_at": row.occurred_at.isoformat(),
        "area": row.event_type.split(".", 1)[0],
        "event_name": row.event_type,
        "actor_type": row.actor_type,
        "actor_id": str(row.actor_id) if row.actor_id else None,
        "target_type": row.target_type,
        "target_id": str(row.target_id) if row.target_id else None,
        "result": row.result,
        "correlation_id": row.correlation_id,
        "details": row.details,
        "event_hash": row.event_hash,
    }


def backup_view(row: BackupRecord) -> dict[str, object]:
    return {
        "id": str(row.id),
        "backup_type": row.backup_type,
        "state": row.state,
        "started_at": row.started_at.isoformat(),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "repository_name": row.repository_name,
        "stanza": row.stanza,
        "backup_label": row.backup_label,
        "manifest_digest": row.manifest_digest,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "restore_tested_at": row.restore_tested_at.isoformat() if row.restore_tested_at else None,
        "size_bytes": row.size_bytes,
        "error_code": row.error_code,
        "version": row.version,
    }


@router.get("/health/live")
async def live():
    return {"status": "ok"}


@router.get("/health/startup")
async def startup(request: Request):
    return {
        "status": "started",
        "version": "1.0.0",
        "specification_revision": "v0021",
        "component": "web",
    }


@router.get("/health/ready")
async def ready(request: Request, session: AsyncSession = Depends(db_session)):
    await session.execute(text("SELECT 1"))
    instance = await session.scalar(
        select(SystemInstance).where(SystemInstance.singleton_key == "primary")
    )
    conversation_setting = await session.scalar(
        select(ApplicationSetting).where(
            ApplicationSetting.area == "models", ApplicationSetting.key == "conversation_model"
        )
    )
    selected_model_id = (
        str(conversation_setting.value.get("value"))
        if conversation_setting and conversation_setting.value.get("value")
        else None
    )
    try:
        selected_model_uuid = UUID(selected_model_id) if selected_model_id else None
    except ValueError:
        selected_model_uuid = None
    selected_model = (
        await session.scalar(
            select(ModelCatalogEntry)
            .join(ProviderConfiguration)
            .where(
                ModelCatalogEntry.id == selected_model_uuid,
                ModelCatalogEntry.available.is_(True),
                ProviderConfiguration.enabled.is_(True),
                ProviderConfiguration.verification_state == "verified",
            )
        )
        if selected_model_id
        else None
    )
    capabilities_ready = bool(
        selected_model
        and selected_model.capabilities.get("responses") is True
        and selected_model.capabilities.get("structured_outputs") is True
    )
    # Bootstrap is operational before an optional model is selected; once a
    # selection exists it must be backed by a verified, capability-complete model.
    ready_state = bool(
        instance
        and instance.state in {"active", "ready"}
        and (selected_model_id is None or capabilities_ready)
    )
    return {
        "status": "ready" if ready_state else "not_ready",
        "instance_state": instance.state if instance else "bootstrap_required",
        "capabilities": {
            "conversation_model": capabilities_ready,
            "selected_model_id": selected_model_id,
        },
        "version": "1.0.0",
    }


@router.get("/metrics")
async def metrics(request: Request):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    required = request.app.state.settings.metrics_token
    if required and token != required.get_secret_value():
        return Response(status_code=404)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/operations/status")
async def status(
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    providers = await session.scalar(
        select(func.count())
        .select_from(ProviderConfiguration)
        .where(
            ProviderConfiguration.enabled.is_(True),
            ProviderConfiguration.verification_state == "verified",
        )
    )
    queued = await session.scalar(
        select(func.count())
        .select_from(BackgroundJob)
        .where(BackgroundJob.state.in_(["queued", "running"]))
    )
    last_backup = await session.scalar(
        select(BackupRecord)
        .where(BackupRecord.state == "completed")
        .order_by(BackupRecord.completed_at.desc())
        .limit(1)
    )
    last_worker_seen = await session.scalar(select(func.max(WorkerHeartbeat.last_seen_at)))
    worker_alive = bool(last_worker_seen and (utc_now() - last_worker_seen).total_seconds() <= 90)
    return {
        "checked_at": utc_now().isoformat(),
        "components": {
            "web": {"state": "ready", "impact": None, "action": None},
            "database": {"state": "ready", "impact": None, "action": None},
            "worker": {
                "state": (
                    "error"
                    if not worker_alive
                    else ("limited" if int(queued or 0) > 100 else "ready")
                ),
                "impact": "Worker nehlásí heartbeat."
                if not worker_alive
                else ("Úlohy mohou být opožděné." if int(queued or 0) > 100 else None),
                "action": "Spusťte nebo zkontrolujte worker."
                if not worker_alive
                else ("Zkontrolujte worker a frontu." if int(queued or 0) > 100 else None),
            },
            "providers": {
                "state": "ready" if int(providers or 0) > 0 else "limited",
                "impact": None
                if int(providers or 0) > 0
                else "AI a hlasové schopnosti nejsou připravené.",
                "action": None
                if int(providers or 0) > 0
                else "Ověřte poskytovatele a vyberte modely.",
            },
            "backups": {
                "state": "ready" if last_backup and last_backup.verified_at else "unknown",
                "impact": None
                if last_backup and last_backup.verified_at
                else "Není doložena ověřená záloha.",
                "action": None
                if last_backup and last_backup.verified_at
                else "Vytvořte a ověřte ruční zálohu.",
            },
        },
        "providers_ready": int(providers or 0),
        "jobs_pending": int(queued or 0),
        "worker_last_seen_at": last_worker_seen.isoformat() if last_worker_seen else None,
        "last_backup": {
            "completed_at": last_backup.completed_at.isoformat()
            if last_backup and last_backup.completed_at
            else None,
            "verified_at": last_backup.verified_at.isoformat()
            if last_backup and last_backup.verified_at
            else None,
        }
        if last_backup
        else None,
    }


@router.get("/operations/audit")
async def audit_list(
    before_id: int | None = Query(default=None, ge=1),
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    area: str | None = Query(default=None, max_length=64),
    result: str | None = Query(default=None, max_length=32),
    actor_type: str | None = Query(default=None, max_length=40),
    target_type: str | None = Query(default=None, max_length=64),
    correlation_id: str | None = Query(default=None, max_length=64),
    event_name: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    conditions = []
    if before_id is not None:
        conditions.append(AuditEvent.id < before_id)
    if from_time is not None:
        conditions.append(AuditEvent.occurred_at >= from_time)
    if to_time is not None:
        conditions.append(AuditEvent.occurred_at <= to_time)
    if area:
        conditions.append(AuditEvent.event_type.startswith(f"{area}."))
    if result:
        conditions.append(AuditEvent.result == result)
    if actor_type:
        conditions.append(AuditEvent.actor_type == actor_type)
    if target_type:
        conditions.append(AuditEvent.target_type == target_type)
    if correlation_id:
        conditions.append(AuditEvent.correlation_id == correlation_id)
    if event_name:
        conditions.append(AuditEvent.event_type == event_name)
    query = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit + 1)
    if conditions:
        query = query.where(and_(*conditions))
    rows = list((await session.scalars(query)).all())
    has_more = len(rows) > limit
    items = rows[:limit]
    return {
        "items": [audit_view(row) for row in items],
        "next_before_id": items[-1].id if has_more and items else None,
    }


@router.get("/operations/audit/integrity")
async def audit_integrity(
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    rows = list((await session.scalars(select(AuditEvent).order_by(AuditEvent.id))).all())
    valid, broken_at = AuditService.verify_chain(rows)
    return {
        "state": "valid" if valid else "broken",
        "events_checked": len(rows),
        "broken_at": broken_at,
        "checked_at": utc_now().isoformat(),
    }


@router.get("/operations/audit/{event_id}")
async def audit_detail(
    event_id: int,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    row = await session.get(AuditEvent, event_id)
    if row is None:
        raise NotFoundError("Auditní událost nebyla nalezena.")
    return audit_view(row)


@router.get("/operations/backups")
async def backups(
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    rows = list(
        (
            await session.scalars(
                select(BackupRecord).order_by(BackupRecord.started_at.desc()).limit(100)
            )
        ).all()
    )
    return {"items": [backup_view(row) for row in rows]}


async def existing_backup_job(
    session: AsyncSession, kind: str, idempotency_key: str
) -> BackgroundJob | None:
    job_id = uuid5(NAMESPACE_URL, f"kajovodagmar:{kind}:{idempotency_key}")
    return await session.get(BackgroundJob, job_id)


@router.post("/operations/backups", status_code=202)
async def create_backup(
    payload: BackupRequest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    previous = await existing_backup_job(session, "backup_create", payload.idempotency_key)
    if previous:
        backup_id = UUID(str(previous.payload["backup_record_id"]))
        row = await session.get(BackupRecord, backup_id)
        if row:
            return backup_view(row)
    row = BackupRecord(
        backup_type="full",
        state="queued",
        started_at=utc_now(),
        repository_name="repo1",
        stanza="kajovodagmar",
        backup_label=f"pending:{payload.purpose}",
    )
    session.add(row)
    await session.flush()
    await request.app.state.jobs.enqueue(
        session,
        "backup_create",
        {"backup_record_id": str(row.id), "purpose": payload.purpose},
        priority=10,
        correlation_id=identity.audit_context.correlation_id,
        job_id=uuid5(NAMESPACE_URL, f"kajovodagmar:backup_create:{payload.idempotency_key}"),
    )
    await request.app.state.audit.append(
        session,
        context=identity.audit_context,
        event_type="backup.requested",
        result="success",
        target_type="backup_record",
        target_id=row.id,
        details={"purpose": payload.purpose},
    )
    BACKUPS.labels("create", "queued").inc()
    return backup_view(row)


async def enqueue_backup_action(
    *,
    kind: str,
    operation: str,
    backup_id: UUID,
    payload: BackupActionRequest,
    request: Request,
    session: AsyncSession,
    identity: RequestIdentity,
) -> BackupRecord:
    previous = await existing_backup_job(session, kind, payload.idempotency_key)
    if previous:
        existing = await session.get(BackupRecord, backup_id)
        if existing:
            return existing
    row = await session.get(BackupRecord, backup_id, with_for_update=True)
    if row is None:
        raise NotFoundError("Záloha nebyla nalezena.")
    if row.version != payload.expected_version:
        raise ConflictError("Záloha se od načtení změnila; načtěte aktuální stav.")
    if row.state != "completed":
        raise ConflictError("Operaci lze provést pouze nad dokončenou zálohou.")
    await request.app.state.jobs.enqueue(
        session,
        kind,
        {"backup_record_id": str(row.id)},
        priority=10,
        correlation_id=identity.audit_context.correlation_id,
        job_id=uuid5(NAMESPACE_URL, f"kajovodagmar:{kind}:{payload.idempotency_key}"),
    )
    await request.app.state.audit.append(
        session,
        context=identity.audit_context,
        event_type=f"backup.{operation}_requested",
        result="success",
        target_type="backup_record",
        target_id=row.id,
    )
    BACKUPS.labels(operation, "queued").inc()
    return row


@router.post("/operations/backups/{backup_id}/verify", status_code=202)
async def verify_backup(
    backup_id: UUID,
    payload: BackupActionRequest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    row = await enqueue_backup_action(
        kind="backup_verify",
        operation="verify",
        backup_id=backup_id,
        payload=payload,
        request=request,
        session=session,
        identity=identity,
    )
    return backup_view(row)


@router.post("/operations/backups/{backup_id}/restore-test", status_code=202)
async def restore_test(
    backup_id: UUID,
    payload: RestoreTestRequest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    row = await enqueue_backup_action(
        kind="backup_restore_test",
        operation="restore_test",
        backup_id=backup_id,
        payload=payload,
        request=request,
        session=session,
        identity=identity,
    )
    return backup_view(row)
