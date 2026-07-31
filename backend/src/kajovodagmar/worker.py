from __future__ import annotations

import asyncio
import hashlib
import os
import socket
from collections.abc import Awaitable, Callable
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from kajovodagmar.audit.service import AuditContext, AuditService
from kajovodagmar.config import get_settings
from kajovodagmar.conversations.service import ConversationService
from kajovodagmar.db.models import (
    ApplicationSetting,
    BackgroundJob,
    Conversation,
    ConversationMessage,
    ConversationSummary,
    MemoryItem,
    ModelCatalogEntry,
    OutboxEvent,
    ProviderConfiguration,
    SearchDocument,
    SearchEmbedding,
)
from kajovodagmar.db.session import Database
from kajovodagmar.errors import CapabilityUnavailableError
from kajovodagmar.files.service import ExportService
from kajovodagmar.history.service import HistoryService
from kajovodagmar.identity.service import IdentityService
from kajovodagmar.jobs.service import JobService
from kajovodagmar.memory.service import MemoryService
from kajovodagmar.notifications.service import NotificationService
from kajovodagmar.observability.logging import configure_logging, get_logger
from kajovodagmar.observability.metrics import JOBS
from kajovodagmar.observability.tracing import configure_tracing, traced
from kajovodagmar.orchestration.service import OrchestrationService
from kajovodagmar.providers.contracts import ChatMessage, ChatRequest
from kajovodagmar.providers.service import ProviderService
from kajovodagmar.search.service import HybridSearchService
from kajovodagmar.security.crypto import SecretCipher
from kajovodagmar.types import utc_now

log = get_logger("kajovodagmar.worker")


class SummaryDecision(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(min_length=1, max_length=10000)


class Worker:
    def __init__(self) -> None:
        settings = get_settings()
        configure_logging(settings.log_level, settings.log_directory)
        configure_tracing(settings, "worker")
        self.database = Database(settings)
        self.jobs = JobService()
        audit = AuditService()
        self.audit = audit
        identity = IdentityService(audit)
        cipher = SecretCipher(settings.root_encryption_key.get_secret_value())
        self.providers = ProviderService(cipher, audit)
        self.notifications = NotificationService(cipher, audit, identity, settings.public_origin)
        self.exports = ExportService(audit, self.jobs, settings.export_directory)
        self.conversations = ConversationService(audit)
        self.memory = MemoryService(audit)
        self.history = HistoryService(audit)
        self.search = HybridSearchService(self.providers)
        self.orchestration = OrchestrationService(
            self.providers, self.conversations, self.memory, self.history, self.search, audit
        )
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self.running = True
        self.handlers: dict[str, Callable[[object, BackgroundJob], Awaitable[None]]] = {
            "memory_index": self.memory_index,
            "conversation_finalize": self.conversation_finalize,
            "conversation_index": self.conversation_index,
            "corrected_turn_reprocess": self.corrected_turn_reprocess,
            "password_reset_notification": self.password_reset_notification,
            "purge_expired": self.purge_expired,
            "export_generate": self.export_generate,
            "search_reindex_all": self.search_reindex_all,
        }

    @traced("worker.run")
    async def run(self) -> None:
        log.info("worker.started", worker_id=self.worker_id)
        try:
            while self.running:
                claimed = 0
                async with self.database.session() as session:
                    claimed += await self.dispatch_outbox(session)
                    jobs = await self.jobs.claim(session, self.worker_id, 10)
                    claimed += len(jobs)
                    for job in jobs:
                        handler = self.handlers.get(job.kind)
                        if handler is None:
                            await self.jobs.fail(job, "unsupported_job_kind")
                            JOBS.labels(job.kind, "failed").inc()
                            continue
                        job_id = job.id
                        job_kind = job.kind
                        try:
                            async with session.begin_nested():
                                await handler(session, job)
                            await self.jobs.complete(job)
                            JOBS.labels(job_kind, "completed").inc()
                        except Exception as exc:
                            await session.refresh(job)
                            await self.jobs.fail(job, exc.__class__.__name__)
                            JOBS.labels(job_kind, "failed").inc()
                            log.exception("job.failed", job_id=str(job_id), kind=job_kind)
                if claimed == 0:
                    await asyncio.sleep(1.0)
        finally:
            await self.database.dispose()
            log.info("worker.stopped", worker_id=self.worker_id)

    async def dispatch_outbox(self, session) -> int:
        events = list(
            (
                await session.scalars(
                    select(OutboxEvent)
                    .where(OutboxEvent.published_at.is_(None))
                    .order_by(OutboxEvent.created_at, OutboxEvent.id)
                    .with_for_update(skip_locked=True)
                    .limit(50)
                )
            ).all()
        )
        for event in events:
            if event.event_type == "memory.index_requested":
                await self.jobs.enqueue(session, "memory_index", event.payload)
            elif event.event_type == "conversation.closed":
                await self.jobs.enqueue(session, "conversation_finalize", event.payload)
                await self.jobs.enqueue(session, "conversation_index", event.payload)
            elif event.event_type == "conversation.corrected_turn_reprocess_requested":
                await self.jobs.enqueue(session, "corrected_turn_reprocess", event.payload)
            event.published_at = utc_now()
            event.attempts += 1
        return len(events)

    async def memory_index(self, session, job: BackgroundJob) -> None:
        memory = await session.get(MemoryItem, UUID(job.payload["memory_id"]))
        if memory is None:
            return
        document = await session.scalar(
            select(SearchDocument)
            .where(SearchDocument.owner_type == "memory", SearchDocument.owner_id == memory.id)
            .with_for_update()
        )
        if document is None:
            document = SearchDocument(
                owner_type="memory",
                owner_id=memory.id,
                account_id=memory.account_id,
                searchable_text=memory.content,
                language="czech",
                source_version=memory.version,
                stale=False,
            )
            session.add(document)
            await session.flush()
        else:
            document.searchable_text = memory.content
            document.source_version = memory.version
            document.stale = False
            document.version += 1
        embedding_setting = await session.scalar(
            select(ApplicationSetting).where(
                ApplicationSetting.area == "models", ApplicationSetting.key == "embedding_model"
            )
        )
        if not embedding_setting or not embedding_setting.value.get("value"):
            return
        model, provider = await self.resolve_model(
            session, UUID(str(embedding_setting.value["value"]))
        )
        runtime = await self.providers.runtime(session, provider)
        vectors = await runtime.embed([memory.content], model=model.external_id)
        if len(vectors) != 1:
            raise RuntimeError("Poskytovatel nevrátil přesně jednu vyhledávací reprezentaci.")
        vector = vectors[0]
        source_hash = hashlib.sha256(memory.content.encode()).hexdigest()
        existing = await session.scalar(
            select(SearchEmbedding)
            .where(
                SearchEmbedding.document_id == document.id,
                SearchEmbedding.model_id == model.external_id,
                SearchEmbedding.source_hash == source_hash,
            )
            .with_for_update()
        )
        serialized = "[" + ",".join(format(float(value), ".9g") for value in vector) + "]"
        if existing is None:
            session.add(
                SearchEmbedding(
                    document_id=document.id,
                    model_id=model.external_id,
                    dimensions=len(vector),
                    embedding_text=memory.content,
                    source_hash=source_hash,
                    vector_data=serialized,
                )
            )
        else:
            existing.vector_data = serialized
            existing.dimensions = len(vector)
            existing.version += 1

    async def conversation_finalize(self, session, job: BackgroundJob) -> None:
        conversation = await session.get(
            Conversation, UUID(job.payload["conversation_id"]), with_for_update=True
        )
        if conversation is None:
            return
        messages = list(
            (
                await session.scalars(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == conversation.id)
                    .order_by(ConversationMessage.sequence)
                )
            ).all()
        )
        if not messages:
            conversation.title = "Prázdný rozhovor"
            conversation.summary = "Rozhovor byl ukončen bez potvrzených replik."
            conversation.title_source = "automatic"
            conversation.summary_source = "automatic"
            return
        setting = await session.scalar(
            select(ApplicationSetting).where(
                ApplicationSetting.area == "models", ApplicationSetting.key == "summary_model"
            )
        )
        if not setting or not setting.value.get("value"):
            raise CapabilityUnavailableError(
                "summary_model", "V Nastavení není vybrán model pro název a shrnutí."
            )
        model, provider_row = await self.resolve_model(session, UUID(str(setting.value["value"])))
        runtime = await self.providers.runtime(session, provider_row)
        transcript = "\n".join(
            f"{('Administrátor' if message.role == 'user' else 'KájovoDagmar')}: {message.content}"
            for message in messages
        )
        request = ChatRequest(
            model=model.external_id,
            messages=(
                ChatMessage(
                    "system",
                    "Vytvoř krátký pravdivý český název a stručné shrnutí "
                    "pouze z doloženého přepisu. "
                    "Neodvozuj nevyřčená fakta, zachovej nejistotu a otevřené body.",
                ),
                ChatMessage("user", transcript[:120000]),
            ),
            response_schema=SummaryDecision.model_json_schema(),
            temperature=0.0,
            timeout_seconds=45.0,
        )
        result = await runtime.chat(request)
        decision = SummaryDecision.model_validate(result.structured)
        conversation.title = decision.title
        conversation.summary = decision.summary
        conversation.title_source = "automatic"
        conversation.summary_source = "automatic"
        conversation.version += 1
        session.add(
            ConversationSummary(
                conversation_id=conversation.id,
                revision_number=conversation.version,
                title=decision.title,
                summary=decision.summary,
                source="automatic",
            )
        )

    async def conversation_index(self, session, job: BackgroundJob) -> None:
        conversation = await session.get(Conversation, UUID(job.payload["conversation_id"]))
        if conversation is None:
            return
        messages = list(
            (
                await session.scalars(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == conversation.id)
                    .order_by(ConversationMessage.sequence)
                )
            ).all()
        )
        transcript = "\n".join(f"{message.role}: {message.content}" for message in messages)
        searchable = "\n".join(
            part
            for part in [conversation.title or "", conversation.summary or "", transcript]
            if part
        ).strip()
        document = await session.scalar(
            select(SearchDocument)
            .where(
                SearchDocument.owner_type == "conversation",
                SearchDocument.owner_id == conversation.id,
            )
            .with_for_update()
        )
        if document is None:
            document = SearchDocument(
                owner_type="conversation",
                owner_id=conversation.id,
                account_id=conversation.account_id,
                searchable_text=searchable,
                language="czech",
                source_version=conversation.version,
                stale=False,
            )
            session.add(document)
            await session.flush()
        else:
            document.searchable_text = searchable
            document.source_version = conversation.version
            document.stale = False
            document.version += 1
        embedding_setting = await session.scalar(
            select(ApplicationSetting).where(
                ApplicationSetting.area == "models", ApplicationSetting.key == "embedding_model"
            )
        )
        if not embedding_setting or not embedding_setting.value.get("value") or not searchable:
            return
        model, provider = await self.resolve_model(
            session, UUID(str(embedding_setting.value["value"]))
        )
        runtime = await self.providers.runtime(session, provider)
        vectors = await runtime.embed([searchable[:120000]], model=model.external_id)
        if len(vectors) != 1:
            raise RuntimeError("Poskytovatel nevrátil přesně jednu vyhledávací reprezentaci.")
        vector = vectors[0]
        source_hash = hashlib.sha256(searchable.encode()).hexdigest()
        existing = await session.scalar(
            select(SearchEmbedding)
            .where(
                SearchEmbedding.document_id == document.id,
                SearchEmbedding.model_id == model.external_id,
                SearchEmbedding.source_hash == source_hash,
            )
            .with_for_update()
        )
        serialized = "[" + ",".join(format(float(value), ".9g") for value in vector) + "]"
        if existing is None:
            session.add(
                SearchEmbedding(
                    document_id=document.id,
                    model_id=model.external_id,
                    dimensions=len(vector),
                    embedding_text=searchable[:120000],
                    source_hash=source_hash,
                    vector_data=serialized,
                )
            )
        else:
            existing.vector_data = serialized
            existing.dimensions = len(vector)
            existing.version += 1

    async def search_reindex_all(self, session, job: BackgroundJob) -> None:
        documents = list(
            (
                await session.scalars(
                    select(SearchDocument)
                    .where(SearchDocument.stale.is_(True))
                    .order_by(SearchDocument.id)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for document in documents:
            payload_key = "memory_id" if document.owner_type == "memory" else "conversation_id"
            if document.owner_type not in {"memory", "conversation"}:
                document.stale = False
                continue
            reindex_job = BackgroundJob(
                kind="reindex_item", payload={payload_key: str(document.owner_id)}
            )
            if document.owner_type == "memory":
                await self.memory_index(session, reindex_job)
            else:
                await self.conversation_index(session, reindex_job)

    async def corrected_turn_reprocess(self, session, job: BackgroundJob) -> None:
        message = await session.get(ConversationMessage, UUID(job.payload["message_id"]))
        if message is None:
            return
        conversation = await session.get(Conversation, message.conversation_id)
        if conversation is None:
            return
        await self.orchestration.answer(
            session,
            conversation.account_id,
            conversation.id,
            message.id,
            AuditContext("system", conversation.account_id, correlation_id=job.correlation_id),
        )
        await self.jobs.enqueue(
            session,
            "conversation_index",
            {"conversation_id": str(conversation.id)},
            correlation_id=job.correlation_id,
        )

    async def password_reset_notification(self, session, job: BackgroundJob) -> None:
        await self.notifications.process_password_reset(session, job.payload)

    async def export_generate(self, session, job: BackgroundJob) -> None:
        await self.exports.generate(session, UUID(job.payload["export_id"]))

    async def purge_expired(self, session, job: BackgroundJob) -> None:
        await session.execute(
            delete(MemoryItem).where(
                MemoryItem.state == "deleted", MemoryItem.purge_after <= utc_now()
            )
        )
        await session.execute(
            delete(Conversation).where(
                Conversation.state == "deleted", Conversation.purge_after <= utc_now()
            )
        )
        await self.exports.purge_expired(session)

    @staticmethod
    async def resolve_model(
        session, model_id: UUID
    ) -> tuple[ModelCatalogEntry, ProviderConfiguration]:
        model = await session.get(ModelCatalogEntry, model_id)
        if model is None or not model.available:
            raise CapabilityUnavailableError("model", "Vybraný model není dostupný.")
        provider = await session.get(ProviderConfiguration, model.provider_id)
        if provider is None or not provider.enabled or provider.verification_state != "verified":
            raise CapabilityUnavailableError(
                "provider", "Poskytovatel vybraného modelu není ověřený a aktivní."
            )
        return model, provider


async def main() -> None:
    await Worker().run()


if __name__ == "__main__":
    asyncio.run(main())
