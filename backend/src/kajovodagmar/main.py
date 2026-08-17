from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from kajovodagmar.api import (
    auth,
    conversations,
    exports,
    history,
    memory,
    notifications,
    operations,
    orchestration,
    profile,
    providers,
    realtime_ticket,
    settings,
    voice_preview,
)
from kajovodagmar.api.middleware import CorrelationAndSecurityMiddleware
from kajovodagmar.audit.service import AuditService
from kajovodagmar.config import get_settings
from kajovodagmar.conversations.service import ConversationService
from kajovodagmar.db.models import ApplicationSetting
from kajovodagmar.db.session import Database
from kajovodagmar.errors import DomainError
from kajovodagmar.files.service import ExportService
from kajovodagmar.history.service import HistoryService
from kajovodagmar.identity.service import IdentityService
from kajovodagmar.jobs.service import JobService
from kajovodagmar.memory.service import MemoryService
from kajovodagmar.notifications.service import NotificationService
from kajovodagmar.observability.logging import configure_logging
from kajovodagmar.observability.tracing import configure_tracing
from kajovodagmar.orchestration.service import OrchestrationService
from kajovodagmar.providers.recommendations import ModelRecommendationService
from kajovodagmar.providers.service import ProviderService
from kajovodagmar.realtime.websocket import handle_realtime
from kajovodagmar.search.service import HybridSearchService
from kajovodagmar.security.crypto import SecretCipher
from kajovodagmar.security.voice_service import sync_key_metadata
from kajovodagmar.settings.catalog import BY_KEY
from kajovodagmar.settings.service import SettingsService


@asynccontextmanager
async def lifespan(app: FastAPI):
    infra = get_settings()
    configure_logging(infra.log_level, infra.log_directory)
    configure_tracing(infra, "web")
    database = Database(infra)
    audit = AuditService()
    cipher = SecretCipher(infra.root_encryption_key.get_secret_value())
    identity = IdentityService(audit)
    conversation_service = ConversationService(audit)
    provider_service = ProviderService(cipher, audit)
    recommendation_service = ModelRecommendationService(audit)
    app.state.settings = infra
    app.state.database = database
    app.state.audit = audit
    app.state.identity = identity
    memory_service = MemoryService(audit)
    history_service = HistoryService(audit)
    search_service = HybridSearchService(provider_service)
    app.state.memory = memory_service
    app.state.history = history_service
    app.state.jobs = JobService()
    app.state.settings_service = SettingsService(audit, provider_service, app.state.jobs)
    app.state.providers = provider_service
    app.state.model_recommendations = recommendation_service
    app.state.search = search_service
    app.state.conversations = conversation_service
    app.state.orchestration = OrchestrationService(
        provider_service,
        conversation_service,
        memory_service,
        history_service,
        search_service,
        audit,
    )
    app.state.exports = ExportService(audit, app.state.jobs, Path(infra.export_directory))
    app.state.notifications = NotificationService(cipher, audit, identity, infra.public_origin)

    async def setting_value(session, area: str, key: str, fallback):
        row = await session.scalar(
            select(ApplicationSetting).where(
                ApplicationSetting.area == area, ApplicationSetting.key == key
            )
        )
        if row is not None:
            return row.value.get("value", fallback)
        definition = BY_KEY.get((area, key))
        return definition.default if definition else fallback

    app.state.setting_value = setting_value
    async with database.session() as session:
        await sync_key_metadata(session, infra.voice_service_api_key_file)
    yield
    await database.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="KájovoDagmar API",
        version="1.0.0",
        description="Kanonické API osobní hlasové virtuální asistentky KájovoDagmar.",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    app.add_middleware(CorrelationAndSecurityMiddleware)

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {"code": exc.code, "message": exc.message, "details": exc.details},
                "correlation_id": getattr(request.state, "correlation_id", None),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errors = []
        for item in exc.errors():
            errors.append(
                {
                    "field": ".".join(str(p) for p in item["loc"]),
                    "message": item["msg"],
                    "type": item["type"],
                }
            )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_failed",
                    "message": "Některé hodnoty nejsou platné.",
                    "details": {"fields": errors},
                },
                "correlation_id": getattr(request.state, "correlation_id", None),
            },
        )

    for router in [
        auth.router,
        conversations.router,
        history.router,
        memory.router,
        settings.router,
        providers.router,
        notifications.router,
        voice_preview.router,
        profile.router,
        realtime_ticket.router,
        exports.router,
        orchestration.router,
    ]:
        app.include_router(router, prefix="/api/v1")
    app.include_router(operations.router, prefix="/api/v1")

    @app.websocket("/api/v1/realtime")
    async def realtime(websocket: WebSocket):
        await handle_realtime(websocket, app)

    static = Path("web/dist")
    if static.exists():
        assets = static / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def frontend(path: str):
            requested = static / path
            if path and requested.is_file() and static.resolve() in requested.resolve().parents:
                return FileResponse(requested)
            return FileResponse(static / "index.html")

    return app


app = create_app()
