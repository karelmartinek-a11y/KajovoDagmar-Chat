from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.api.dependencies import RequestIdentity, csrf_guard, current_identity, db_session
from kajovodagmar.api.serializers import model_view
from kajovodagmar.errors import ConflictError
from kajovodagmar.files.schemas import ExportRequest
from kajovodagmar.types import utc_now

router = APIRouter(prefix="/exports", tags=["exports"])
FIELDS = (
    "id",
    "kind",
    "state",
    "format",
    "scope",
    "file_digest",
    "expires_at",
    "completed_at",
    "error_code",
    "version",
)


@router.post("", status_code=202)
async def create_export(
    payload: ExportRequest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    row = await request.app.state.exports.request(
        session,
        identity.account.id,
        kind=payload.kind,
        format=payload.format,
        scope=payload.scope,
        context=identity.audit_context,
    )
    return model_view(row, *FIELDS)


@router.get("")
async def list_exports(
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    rows = await request.app.state.exports.list(session, identity.account.id)
    return {"items": [model_view(row, *FIELDS) for row in rows]}


@router.get("/{export_id}")
async def export_status(
    export_id: UUID,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    row = await request.app.state.exports.get(session, identity.account.id, export_id)
    return model_view(row, *FIELDS)


@router.get("/{export_id}/download")
async def download_export(
    export_id: UUID,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(current_identity),
):
    row = await request.app.state.exports.get(session, identity.account.id, export_id)
    if row.expires_at and row.expires_at <= utc_now():
        raise ConflictError("Export již vypršel.")
    if row.state != "completed" or not row.file_path:
        raise ConflictError("Export ještě není připraven ke stažení.")
    path = Path(row.file_path).resolve()
    root = request.app.state.exports.export_root
    if root not in path.parents or not path.is_file():
        raise ConflictError("Soubor exportu není dostupný.")
    suffix = row.format if row.format != "markdown" else "md"
    return FileResponse(
        path,
        filename=f"kajovodagmar-{row.kind}-{row.id}.{suffix}",
        media_type="application/json" if row.format == "json" else "text/markdown; charset=utf-8",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
