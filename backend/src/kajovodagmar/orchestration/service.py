from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from time import perf_counter
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.audit.service import AuditContext, AuditService
from kajovodagmar.conversations.service import ConversationService
from kajovodagmar.db.models import (
    ApplicationSetting,
    Conversation,
    ConversationMessage,
    MemoryItem,
    MemorySource,
    ModelCatalogEntry,
    OrchestrationAttempt,
    OrchestrationRun,
    ProviderConfiguration,
    ToolAction,
)
from kajovodagmar.errors import (
    CapabilityUnavailableError,
    ConflictError,
    DomainError,
    NotFoundError,
)
from kajovodagmar.history.schemas import HistorySearch
from kajovodagmar.history.service import HistoryService
from kajovodagmar.memory.schemas import MemoryCreate, MemorySearch, MemoryUpdate
from kajovodagmar.memory.service import MemoryService
from kajovodagmar.observability.tracing import traced
from kajovodagmar.orchestration.contracts import ModelDecision, ToolCallDecision
from kajovodagmar.orchestration.prompts import (
    ORCHESTRATION_VERSION,
    PROMPT_VERSION,
    SYSTEM_TEMPLATE,
)
from kajovodagmar.providers.contracts import ChatMessage, ChatRequest, ChatResult
from kajovodagmar.providers.service import ProviderService
from kajovodagmar.search.service import HybridSearchService
from kajovodagmar.types import utc_now

READ_ONLY_TOOLS = {"memory_search", "history_search"}
STATE_TOOLS = {
    "memory_create",
    "memory_update",
    "memory_mark_outdated",
    "memory_delete",
    "memory_restore",
    "memory_merge",
    "history_continue",
    "history_delete",
    "history_restore",
}


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    run_id: UUID
    message: ConversationMessage
    decision: ModelDecision
    actions: tuple[ToolAction, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextBundle:
    prompt: str
    manifest: dict[str, Any]
    allowed_source_ids: frozenset[str]


class OrchestrationService:
    def __init__(
        self,
        providers: ProviderService,
        conversations: ConversationService,
        memory: MemoryService,
        history: HistoryService,
        search: HybridSearchService,
        audit: AuditService,
    ) -> None:
        self.providers = providers
        self.conversations = conversations
        self.memory = memory
        self.history = history
        self.search = search
        self.audit = audit
        self.adapter = TypeAdapter(ModelDecision)

    @traced("orchestration.answer")
    async def answer(
        self,
        session: AsyncSession,
        account_id: UUID,
        conversation_id: UUID,
        user_message_id: UUID,
        context: AuditContext | None = None,
    ) -> OrchestrationResult:
        audit_context = context or AuditContext("system", account_id)
        existing = await session.scalar(
            select(OrchestrationRun)
            .where(
                OrchestrationRun.source_message_id == user_message_id,
                OrchestrationRun.account_id == account_id,
            )
            .with_for_update()
        )
        if (
            existing
            and existing.state == "completed"
            and existing.response_message_id
            and existing.decision
        ):
            message = await session.get(ConversationMessage, existing.response_message_id)
            if message is None:
                raise DomainError(
                    "orchestration_integrity", "Dokončený run nemá dostupnou odpověď.", 500
                )
            actions = tuple(
                (
                    await session.scalars(
                        select(ToolAction)
                        .where(ToolAction.run_id == existing.id)
                        .order_by(ToolAction.created_at)
                    )
                ).all()
            )
            return OrchestrationResult(
                existing.id, message, self.adapter.validate_python(existing.decision), actions
            )
        if existing and existing.state in {"running", "awaiting_confirmation"}:
            raise ConflictError("Tato replika se již zpracovává.", {"run_id": str(existing.id)})

        conversation = await session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.account_id == account_id
            )
        )
        if conversation is None:
            raise NotFoundError("Konverzace nebyla nalezena.")
        messages = list(
            (
                await session.scalars(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == conversation_id)
                    .order_by(ConversationMessage.sequence)
                )
            ).all()
        )
        source_message = next(
            (message for message in messages if message.id == user_message_id), None
        )
        if source_message is None or source_message.role != "user":
            raise NotFoundError("Zdrojová uživatelská replika nebyla nalezena.")
        normalized_input = self._normalize(source_message.content)
        provider_row, model_row = await self._primary_model(session)
        bundle = await self._build_context(
            session,
            account_id=account_id,
            conversation=conversation,
            messages=messages,
            source_message=source_message,
            normalized_input=normalized_input,
            tool_results=[],
        )
        run = existing or OrchestrationRun(
            account_id=account_id,
            conversation_id=conversation_id,
            source_message_id=user_message_id,
            state="running",
            orchestration_version=ORCHESTRATION_VERSION,
            prompt_version=PROMPT_VERSION,
            provider_id=provider_row.id,
            model_id=model_row.id,
            context_manifest=bundle.manifest,
            usage={},
        )
        session.add(run)
        await session.flush()
        try:
            first, first_result = await self._call_model(
                session, run, provider_row, model_row, bundle.prompt, messages, temperature=0.15
            )
            read_calls = [tool for tool in first.tool_calls if tool.name in READ_ONLY_TOOLS]
            decision = first
            result_usage = self._usage(first_result)
            allowed_ids = set(bundle.allowed_source_ids)
            if read_calls:
                tool_results, tool_source_ids = await self._execute_read_tools(
                    session, account_id, read_calls
                )
                allowed_ids.update(tool_source_ids)
                second_bundle = await self._build_context(
                    session,
                    account_id=account_id,
                    conversation=conversation,
                    messages=messages,
                    source_message=source_message,
                    normalized_input=normalized_input,
                    tool_results=tool_results,
                )
                run.context_manifest = second_bundle.manifest
                allowed_ids.update(second_bundle.allowed_source_ids)
                decision, second_result = await self._call_model(
                    session,
                    run,
                    provider_row,
                    model_row,
                    second_bundle.prompt,
                    messages,
                    temperature=0.15,
                )
                result_usage = self._merge_usage(result_usage, self._usage(second_result))
                if any(tool.name in READ_ONLY_TOOLS for tool in decision.tool_calls):
                    raise DomainError(
                        "tool_loop_exceeded",
                        "Model po ověřeném hledání znovu požadoval stejný nástroj.",
                        502,
                    )
            self._validate_sources(decision, allowed_ids)
            actions = tuple(
                await self._create_actions(
                    session,
                    run=run,
                    account_id=account_id,
                    conversation=conversation,
                    source_message=source_message,
                    decision=decision,
                )
            )
            run.intent = decision.intent
            run.decision = decision.model_dump(mode="json")
            run.usage = result_usage
            run.state = "awaiting_confirmation" if actions else "completed"
            idem = hashlib.sha256(
                f"assistant:{conversation_id}:{user_message_id}:{run.id}".encode()
            ).hexdigest()
            message = await self.conversations.add_assistant_turn(
                session, conversation_id, decision.answer, idem, run.id
            )
            run.response_message_id = message.id
            if not actions:
                run.completed_at = utc_now()
            run.version += 1
            await self.audit.append(
                session,
                context=audit_context,
                event_type="orchestration.completed",
                result="success",
                target_type="orchestration_run",
                target_id=run.id,
                details={
                    "intent": decision.intent,
                    "attempts": run.attempt_count,
                    "actions": len(actions),
                    "prompt_version": PROMPT_VERSION,
                },
            )
            return OrchestrationResult(run.id, message, decision, tuple(actions))
        except Exception as exc:
            run.state = "failed"
            run.error_code = getattr(exc, "code", exc.__class__.__name__)
            run.completed_at = utc_now()
            run.version += 1
            await self.audit.append(
                session,
                context=audit_context,
                event_type="orchestration.failed",
                result="failed",
                target_type="orchestration_run",
                target_id=run.id,
                details={"error_code": run.error_code, "attempts": run.attempt_count},
            )
            if isinstance(exc, DomainError):
                exc.durable = True
            raise

    async def confirm_action(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        action_id: UUID,
        expected_action_version: int,
        context: AuditContext,
    ) -> ToolAction:
        action = await session.scalar(
            select(ToolAction)
            .join(OrchestrationRun, OrchestrationRun.id == ToolAction.run_id)
            .where(ToolAction.id == action_id, OrchestrationRun.account_id == account_id)
            .with_for_update()
        )
        if action is None:
            raise NotFoundError("Potvrzovaná operace nebyla nalezena.")
        if action.state == "completed":
            return action
        if action.version != expected_action_version:
            raise ConflictError(
                "Návrh operace byl mezitím změněn.",
                {"expected_version": expected_action_version, "actual_version": action.version},
            )
        if action.state != "pending_confirmation":
            raise ConflictError("Operaci v tomto stavu nelze potvrdit.")
        if action.expires_at and action.expires_at <= utc_now():
            action.state = "expired"
            action.version += 1
            expired = ConflictError("Platnost potvrzení vypršela; vyžádejte nový náhled.")
            expired.durable = True
            raise expired
        action.state = "running"
        action.confirmed_at = utc_now()
        action.version += 1
        try:
            result = await self._execute_state_action(session, account_id, action, context)
            action.result = result
            action.state = "completed"
            action.completed_at = utc_now()
            action.version += 1
            run = await session.get(OrchestrationRun, action.run_id, with_for_update=True)
            if run is not None:
                remaining = await session.scalar(
                    select(ToolAction.id)
                    .where(
                        ToolAction.run_id == run.id,
                        ToolAction.id != action.id,
                        ToolAction.state.not_in(["completed", "failed", "expired", "cancelled"]),
                    )
                    .limit(1)
                )
                if remaining is None:
                    run.state = "completed"
                    run.version += 1
            await self.audit.append(
                session,
                context=context,
                event_type="orchestration.action_completed",
                result="success",
                target_type="tool_action",
                target_id=action.id,
                details={"name": action.name, "run_id": str(action.run_id)},
            )
            return action
        except Exception as exc:
            action.state = "failed"
            action.error_code = getattr(exc, "code", exc.__class__.__name__)
            action.version += 1
            await self.audit.append(
                session,
                context=context,
                event_type="orchestration.action_failed",
                result="failed",
                target_type="tool_action",
                target_id=action.id,
                details={"name": action.name, "error_code": action.error_code},
            )
            if isinstance(exc, DomainError):
                exc.durable = True
            raise

    async def cancel_run(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        run_id: UUID,
        context: AuditContext,
    ) -> OrchestrationRun:
        run = await session.scalar(
            select(OrchestrationRun)
            .where(OrchestrationRun.id == run_id, OrchestrationRun.account_id == account_id)
            .with_for_update()
        )
        if run is None:
            raise NotFoundError("Orchestration run nebyl nalezen.")
        if run.state in {"completed", "failed", "cancelled"}:
            return run
        run.state = "cancelled"
        run.cancelled_at = utc_now()
        run.version += 1
        actions = list(
            (
                await session.scalars(
                    select(ToolAction)
                    .where(ToolAction.run_id == run.id, ToolAction.state == "pending_confirmation")
                    .with_for_update()
                )
            ).all()
        )
        for action in actions:
            action.state = "cancelled"
            action.version += 1
        await self.audit.append(
            session,
            context=context,
            event_type="orchestration.cancelled",
            result="success",
            target_type="orchestration_run",
            target_id=run.id,
        )
        return run

    async def _call_model(
        self,
        session: AsyncSession,
        run: OrchestrationRun,
        provider_row: ProviderConfiguration,
        model_row: ModelCatalogEntry,
        prompt: str,
        messages: list[ConversationMessage],
        *,
        temperature: float,
    ) -> tuple[ModelDecision, ChatResult]:
        provider = await self.providers.runtime(session, provider_row)
        run.attempt_count += 1
        attempt = OrchestrationAttempt(
            run_id=run.id,
            attempt_number=run.attempt_count,
            provider_id=provider_row.id,
            model_id=model_row.id,
            state="running",
            usage={},
        )
        session.add(attempt)
        await session.flush()
        request_messages = [ChatMessage("system", prompt)]
        request_messages.extend(
            ChatMessage(message.role, message.content) for message in messages[-30:]
        )
        request = ChatRequest(
            model=model_row.external_id,
            messages=tuple(request_messages),
            response_schema=ModelDecision.model_json_schema(),
            temperature=temperature,
            timeout_seconds=45.0,
            capabilities=model_row.capabilities,
        )
        started = perf_counter()
        try:
            result = await provider.chat(request)
            try:
                decision = self.adapter.validate_python(result.structured)
            except ValidationError as exc:
                validation_errors = [
                    {
                        "path": ".".join(str(part) for part in error["loc"]),
                        "type": str(error["type"]),
                    }
                    for error in exc.errors()
                ]
                raise DomainError(
                    "model_decision_invalid",
                    "Modelová odpověď nesplnila bezpečný interní kontrakt.",
                    502,
                    {"validation_errors": validation_errors},
                ) from exc
            attempt.state = "completed"
            attempt.provider_response_id = result.provider_response_id
            attempt.completed_at = utc_now()
            attempt.latency_ms = round((perf_counter() - started) * 1000)
            attempt.usage = self._usage(result)
            return decision, result
        except Exception as exc:
            attempt.state = "failed"
            attempt.completed_at = utc_now()
            attempt.latency_ms = round((perf_counter() - started) * 1000)
            attempt.error_code = getattr(exc, "code", exc.__class__.__name__)
            raise

    async def _build_context(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        conversation: Conversation,
        messages: list[ConversationMessage],
        source_message: ConversationMessage,
        normalized_input: str,
        tool_results: list[dict[str, Any]],
    ) -> ContextBundle:
        ranked = await self.search.ranked_owner_ids(
            session,
            account_id=account_id,
            owner_type="memory",
            query=normalized_input,
            limit=12,
        )
        memory_query = select(MemoryItem).where(
            MemoryItem.account_id == account_id,
            MemoryItem.state == "active",
        )
        if ranked:
            memory_query = memory_query.where(MemoryItem.id.in_(ranked)).order_by(
                case({value: index for index, value in enumerate(ranked)}, value=MemoryItem.id)
            )
        else:
            memory_query = memory_query.order_by(MemoryItem.updated_at.desc()).limit(6)
        memories = list((await session.scalars(memory_query)).all())[:12]
        sources = (
            list(
                (
                    await session.scalars(
                        select(MemorySource).where(
                            MemorySource.memory_id.in_([m.id for m in memories])
                        )
                    )
                ).all()
            )
            if memories
            else []
        )
        source_by_memory: dict[UUID, list[MemorySource]] = {}
        for source in sources:
            source_by_memory.setdefault(source.memory_id, []).append(source)
        memory_payload = []
        for memory in memories:
            memory_payload.append(
                {
                    "id": str(memory.id),
                    "category": memory.category,
                    "state": memory.state,
                    "content": memory.content,
                    "event_at": memory.event_at.isoformat() if memory.event_at else None,
                    "valid_from": memory.valid_from.isoformat() if memory.valid_from else None,
                    "valid_until": memory.valid_until.isoformat() if memory.valid_until else None,
                    "sources": [
                        {
                            "type": source.source_type,
                            "conversation_id": str(source.conversation_id)
                            if source.conversation_id
                            else None,
                            "message_id": str(source.message_id) if source.message_id else None,
                        }
                        for source in source_by_memory.get(memory.id, [])
                    ],
                }
            )
        selected_messages = self._context_messages(messages, 45_000)
        conversation_payload = [
            {
                "id": str(message.id),
                "sequence": message.sequence,
                "role": message.role,
                "content": message.content,
                "status": message.status,
            }
            for message in selected_messages
        ]
        allowed = {str(message.id) for message in selected_messages}
        allowed.update(str(memory.id) for memory in memories)
        for result in tool_results:
            allowed.update(
                str(item.get("id")) for item in result.get("items", []) if item.get("id")
            )
        manifest = {
            "orchestration_version": ORCHESTRATION_VERSION,
            "prompt_version": PROMPT_VERSION,
            "conversation_id": str(conversation.id),
            "source_message_id": str(source_message.id),
            "sources": {
                "conversation_messages": [str(message.id) for message in selected_messages],
                "memory_items": [str(memory.id) for memory in memories],
                "tool_results": [result.get("tool") for result in tool_results],
            },
            "classes": ["system_rules", "active_conversation", "confirmed_memory"]
            + (["verified_tool_result"] if tool_results else []),
        }
        verbosity = await self._setting(session, "conversation", "verbosity", "balanced")
        prompt = SYSTEM_TEMPLATE.format(
            language=conversation.language,
            verbosity=verbosity,
            context_manifest=json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
            conversation_summary=conversation.context_summary or "Není vytvořen řízený souhrn.",
            conversation=json.dumps(
                conversation_payload, ensure_ascii=False, separators=(",", ":")
            ),
            memories=json.dumps(memory_payload, ensure_ascii=False, separators=(",", ":")),
            tool_results=json.dumps(tool_results, ensure_ascii=False, separators=(",", ":"))
            if tool_results
            else "Žádný nástroj nebyl spuštěn.",
        )
        return ContextBundle(prompt, manifest, frozenset(allowed))

    async def _execute_read_tools(
        self,
        session: AsyncSession,
        account_id: UUID,
        calls: list[ToolCallDecision],
    ) -> tuple[list[dict[str, Any]], set[str]]:
        results: list[dict[str, Any]] = []
        source_ids: set[str] = set()
        for call in calls[:5]:
            query = self._normalize(str(call.arguments.get("query", "")))
            if not query:
                raise DomainError(
                    "tool_arguments_invalid", "Hledací nástroj nemá platný dotaz.", 502
                )
            raw_limit = call.arguments.get("limit", 8)
            if isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
                raise DomainError(
                    "tool_arguments_invalid", "Limit nástroje musí být celé číslo.", 502
                )
            limit = min(max(raw_limit, 1), 20)
            if call.name == "memory_search":
                ranked = await self.search.ranked_owner_ids(
                    session, account_id=account_id, owner_type="memory", query=query, limit=limit
                )
                memory_request = MemorySearch(query=query, states=["active"], limit=limit)
                memory_rows = await self.memory.search(session, account_id, memory_request, ranked)
                items = [
                    {
                        "id": str(row.id),
                        "content": row.content,
                        "category": row.category,
                        "state": row.state,
                        "event_at": row.event_at.isoformat() if row.event_at else None,
                    }
                    for row in memory_rows
                ]
            elif call.name == "history_search":
                ranked = await self.search.ranked_owner_ids(
                    session,
                    account_id=account_id,
                    owner_type="conversation",
                    query=query,
                    limit=limit,
                )
                history_request = HistorySearch(query=query, limit=limit)
                history_rows = await self.history.search(
                    session, account_id, history_request, ranked
                )
                items = [
                    {
                        "id": str(row.id),
                        "title": row.title,
                        "summary": row.summary,
                        "started_at": row.started_at.isoformat(),
                        "state": row.state,
                    }
                    for row in history_rows
                ]
            else:
                continue
            source_ids.update(str(item["id"]) for item in items if item.get("id") is not None)
            results.append({"tool": call.name, "query": query, "scope": "global", "items": items})
        return results, source_ids

    async def _create_actions(
        self,
        session: AsyncSession,
        *,
        run: OrchestrationRun,
        account_id: UUID,
        conversation: Conversation,
        source_message: ConversationMessage,
        decision: ModelDecision,
    ) -> list[ToolAction]:
        calls = [tool for tool in decision.tool_calls if tool.name in STATE_TOOLS]
        if decision.memory_proposal and not any(tool.name == "memory_create" for tool in calls):
            calls.append(
                ToolCallDecision(
                    name="memory_create",
                    arguments=decision.memory_proposal.model_dump(exclude_none=True),
                )
            )
        if calls and not decision.requires_confirmation:
            raise DomainError(
                "confirmation_missing", "Stavová operace nemá povinné potvrzení.", 502
            )
        actions: list[ToolAction] = []
        for index, call in enumerate(calls):
            arguments, preview, target_version = await self._normalize_action(
                session, account_id, call, conversation, source_message
            )
            encoded = json.dumps(
                arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            digest = hashlib.sha256(encoded.encode()).hexdigest()
            action = ToolAction(
                run_id=run.id,
                name=call.name,
                arguments=arguments,
                arguments_hash=digest,
                side_effect="state_change",
                confirmation_required=True,
                state="pending_confirmation",
                preview=preview,
                expected_target_version=target_version,
                expires_at=utc_now() + timedelta(minutes=10),
                idempotency_key=hashlib.sha256(
                    f"{run.id}:{index}:{call.name}:{digest}".encode()
                ).hexdigest(),
            )
            session.add(action)
            actions.append(action)
        await session.flush()
        return actions

    async def _normalize_action(
        self,
        session: AsyncSession,
        account_id: UUID,
        call: ToolCallDecision,
        conversation: Conversation,
        source_message: ConversationMessage,
    ) -> tuple[dict[str, Any], dict[str, Any], int | None]:
        args = dict(call.arguments)
        if call.name == "memory_create":
            content = self._normalize(str(args.get("content", "")))
            category = str(args.get("category", "other"))
            request = MemoryCreate(
                content=content,
                category=category,  # type: ignore[arg-type]
                origin_type="explicit_command",
                source_conversation_id=conversation.id,
                source_message_id=source_message.id,
                original_expression=source_message.content,
                event_at=args.get("event_at"),
                valid_from=args.get("valid_from"),
                valid_until=args.get("valid_until"),
                confirmed=True,
            )
            normalized = request.model_dump(mode="json")
            return (
                normalized,
                {
                    "operation": "Uložit paměť",
                    "content": content,
                    "category": category,
                    "impact": "Vznikne aktivní paměťová položka.",
                },
                None,
            )
        if call.name in {
            "memory_update",
            "memory_mark_outdated",
            "memory_delete",
            "memory_restore",
        }:
            try:
                memory_id = UUID(str(args.get("memory_id")))
            except (ValueError, AttributeError, TypeError) as exc:
                raise DomainError(
                    "tool_arguments_invalid", "Identifikátor paměti není platné UUID.", 502
                ) from exc
            item = await self.memory.get(session, account_id, memory_id, include_deleted=True)
            expected_value = args.get("expected_version", item.version)
            if isinstance(expected_value, bool) or not isinstance(expected_value, int):
                raise DomainError(
                    "tool_arguments_invalid", "Verze paměti musí být celé číslo.", 502
                )
            expected = expected_value
            if expected != item.version:
                raise ConflictError(
                    "Cílová paměť se změnila před vytvořením náhledu.",
                    {"actual_version": item.version},
                )
            normalized = {"memory_id": str(item.id), "expected_version": item.version}
            if call.name == "memory_update":
                for key in ("content", "category", "event_at", "valid_from", "valid_until"):
                    if key in args:
                        normalized[key] = args[key]
            return (
                normalized,
                {
                    "operation": call.name,
                    "target": item.content,
                    "state": item.state,
                    "impact": self._impact(call.name),
                },
                item.version,
            )
        if call.name == "memory_merge":
            raw_source_ids = args.get("source_ids", [])
            if not isinstance(raw_source_ids, list):
                raise DomainError("tool_arguments_invalid", "source_ids musí být seznam UUID.", 502)
            try:
                source_ids = [UUID(str(value)) for value in raw_source_ids]
            except (ValueError, AttributeError, TypeError) as exc:
                raise DomainError(
                    "tool_arguments_invalid", "source_ids obsahuje neplatné UUID.", 502
                ) from exc
            if len(set(source_ids)) < 2:
                raise DomainError(
                    "tool_arguments_invalid", "Sloučení vyžaduje nejméně dvě položky.", 502
                )
            sources = list(
                (
                    await session.scalars(
                        select(MemoryItem).where(
                            MemoryItem.account_id == account_id, MemoryItem.id.in_(source_ids)
                        )
                    )
                ).all()
            )
            if len(sources) != len(set(source_ids)):
                raise NotFoundError("Některá slučovaná paměť nebyla nalezena.")
            merge_request = MemoryCreate(
                content=self._normalize(str(args.get("content", ""))),
                category=str(args.get("category", "other")),  # type: ignore[arg-type]
                origin_type="explicit_command",
                source_conversation_id=conversation.id,
                source_message_id=source_message.id,
                confirmed=True,
            )
            normalized = {
                "source_ids": [str(value) for value in source_ids],
                "target": merge_request.model_dump(mode="json"),
                "source_versions": {str(row.id): row.version for row in sources},
            }
            return (
                normalized,
                {
                    "operation": "Sloučit paměti",
                    "sources": [row.content for row in sources],
                    "result": merge_request.content,
                    "impact": "Zdrojové položky budou označeny jako sloučené.",
                },
                None,
            )
        if call.name in {"history_continue", "history_delete", "history_restore"}:
            try:
                conversation_id = UUID(str(args.get("conversation_id")))
            except (ValueError, AttributeError, TypeError) as exc:
                raise DomainError(
                    "tool_arguments_invalid", "Identifikátor konverzace není platné UUID.", 502
                ) from exc
            conversation_target, _ = await self.history.detail(
                session, account_id, conversation_id, include_deleted=True
            )
            expected_value = args.get("expected_version")
            expected = conversation_target.version if expected_value is None else expected_value
            if isinstance(expected, bool) or not isinstance(expected, int):
                raise DomainError(
                    "tool_arguments_invalid", "Verze konverzace musí být celé číslo.", 502
                )
            if expected != conversation_target.version:
                raise ConflictError(
                    "Cílová konverzace se změnila před vytvořením náhledu.",
                    {"actual_version": conversation_target.version},
                )
            normalized = {
                "conversation_id": str(conversation_target.id),
                "expected_version": conversation_target.version,
            }
            return (
                normalized,
                {
                    "operation": call.name,
                    "target": conversation_target.title or str(conversation_target.id),
                    "state": conversation_target.state,
                    "impact": self._impact(call.name),
                },
                conversation_target.version,
            )
        raise DomainError("tool_not_allowed", "Požadovaný nástroj není pro tento run povolen.", 502)

    async def _execute_state_action(
        self,
        session: AsyncSession,
        account_id: UUID,
        action: ToolAction,
        context: AuditContext,
    ) -> dict[str, Any]:
        args = action.arguments
        if (
            hashlib.sha256(
                json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            != action.arguments_hash
        ):
            raise DomainError(
                "action_integrity_failed", "Integrita potvrzované operace byla porušena.", 409
            )
        if action.name == "memory_create":
            created_memory = await self.memory.create(
                session, account_id, MemoryCreate.model_validate(args), context
            )
            return {
                "memory_id": str(created_memory.id),
                "state": created_memory.state,
                "version": created_memory.version,
            }
        if action.name in {"memory_update", "memory_mark_outdated"}:
            memory_id = UUID(args["memory_id"])
            update = MemoryUpdate(
                expected_version=int(args["expected_version"]),
                content=args.get("content"),
                category=args.get("category"),
                event_at=args.get("event_at"),
                valid_from=args.get("valid_from"),
                valid_until=args.get("valid_until"),
                mark_outdated=action.name == "memory_mark_outdated",
            )
            updated_memory = await self.memory.update(
                session, account_id, memory_id, update, context
            )
            return {
                "memory_id": str(updated_memory.id),
                "state": updated_memory.state,
                "version": updated_memory.version,
            }
        if action.name == "memory_delete":
            retention = int(await self._setting(session, "memory", "soft_delete_days", 30))
            deleted_memory = await self.memory.soft_delete(
                session,
                account_id,
                UUID(args["memory_id"]),
                int(args["expected_version"]),
                retention,
                context,
            )
            return {
                "memory_id": str(deleted_memory.id),
                "state": deleted_memory.state,
                "version": deleted_memory.version,
                "recoverable_until": (
                    deleted_memory.purge_after.isoformat() if deleted_memory.purge_after else None
                ),
            }
        if action.name == "memory_restore":
            restored_memory = await self.memory.restore(
                session, account_id, UUID(args["memory_id"]), int(args["expected_version"]), context
            )
            return {
                "memory_id": str(restored_memory.id),
                "state": restored_memory.state,
                "version": restored_memory.version,
            }
        if action.name == "memory_merge":
            for source_id, expected in args["source_versions"].items():
                source = await self.memory.get(
                    session, account_id, UUID(source_id), include_deleted=True
                )
                if source.version != expected:
                    raise ConflictError(
                        "Některá zdrojová paměť se před potvrzením změnila.",
                        {"memory_id": source_id},
                    )
            merged_memory = await self.memory.merge(
                session,
                account_id,
                [UUID(value) for value in args["source_ids"]],
                MemoryCreate.model_validate(args["target"]),
                context,
            )
            return {
                "memory_id": str(merged_memory.id),
                "state": merged_memory.state,
                "version": merged_memory.version,
            }
        if action.name == "history_continue":
            continued_conversation = await self.history.continue_from(
                session, account_id, UUID(args["conversation_id"]), context
            )
            return {
                "conversation_id": str(continued_conversation.id),
                "state": continued_conversation.state,
                "version": continued_conversation.version,
            }
        if action.name == "history_delete":
            retention = int(await self._setting(session, "history", "soft_delete_days", 30))
            deleted_conversation = await self.history.soft_delete(
                session,
                account_id,
                UUID(args["conversation_id"]),
                int(args["expected_version"]),
                retention,
                context,
            )
            return {
                "conversation_id": str(deleted_conversation.id),
                "state": deleted_conversation.state,
                "version": deleted_conversation.version,
                "recoverable_until": (
                    deleted_conversation.purge_after.isoformat()
                    if deleted_conversation.purge_after
                    else None
                ),
            }
        if action.name == "history_restore":
            restored_conversation = await self.history.restore(
                session,
                account_id,
                UUID(args["conversation_id"]),
                int(args["expected_version"]),
                context,
            )
            return {
                "conversation_id": str(restored_conversation.id),
                "state": restored_conversation.state,
                "version": restored_conversation.version,
            }
        raise DomainError("tool_not_allowed", "Potvrzený nástroj není podporován.", 409)

    async def _primary_model(
        self, session: AsyncSession
    ) -> tuple[ProviderConfiguration, ModelCatalogEntry]:
        setting = await session.scalar(
            select(ApplicationSetting).where(
                ApplicationSetting.area == "models",
                ApplicationSetting.key == "conversation_model",
            )
        )
        if setting is None or not setting.value.get("value"):
            raise CapabilityUnavailableError(
                "conversation_model", "V Nastavení není vybrán primární konverzační model."
            )
        try:
            model_uuid = UUID(str(setting.value["value"]))
        except ValueError as exc:
            raise CapabilityUnavailableError(
                "conversation_model", "Uložený výběr modelu není platný."
            ) from exc
        model = await session.get(ModelCatalogEntry, model_uuid)
        if model is None or not model.available:
            raise CapabilityUnavailableError("conversation_model", "Vybraný model není dostupný.")
        required = {"responses", "structured_outputs"}
        if not required.issubset(
            key for key, enabled in (model.capabilities or {}).items() if enabled is True
        ):
            raise CapabilityUnavailableError(
                "conversation_model",
                "Vybraný model nemá ověřenou schopnost strukturované konverzační odpovědi.",
            )
        provider = await session.get(ProviderConfiguration, model.provider_id)
        if provider is None or not provider.enabled or provider.verification_state != "verified":
            raise CapabilityUnavailableError(
                "conversation_model", "Poskytovatel modelu není ověřen a aktivní."
            )
        return provider, model

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFC", value)
        return " ".join(normalized.split()).strip()

    @staticmethod
    def _context_messages(
        messages: list[ConversationMessage], max_characters: int
    ) -> list[ConversationMessage]:
        selected: list[ConversationMessage] = []
        used = 0
        for message in reversed(messages):
            length = len(message.content)
            if selected and used + length > max_characters:
                break
            selected.append(message)
            used += length
        return list(reversed(selected))

    @staticmethod
    def _validate_sources(decision: ModelDecision, allowed_ids: set[str]) -> None:
        invalid = [
            source.source_id for source in decision.sources if source.source_id not in allowed_ids
        ]
        if invalid:
            raise DomainError(
                "source_provenance_invalid",
                "Model odkázal na zdroj, který nebyl součástí řízeného kontextu.",
                502,
                {"invalid_source_count": len(invalid)},
            )

    @staticmethod
    def _usage(result: ChatResult) -> dict[str, int]:
        return {
            "input_units": int(result.input_units or 0),
            "output_units": int(result.output_units or 0),
        }

    @staticmethod
    def _merge_usage(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
        return {
            key: int(left.get(key, 0)) + int(right.get(key, 0))
            for key in {"input_units", "output_units"}
        }

    @staticmethod
    def _impact(name: str) -> str:
        return {
            "memory_update": "Položka dostane novou auditovatelnou verzi.",
            "memory_mark_outdated": "Položka se přestane používat jako současný fakt.",
            "memory_delete": (
                "Položka se přestane používat a bude obnovitelná jen po retenční dobu."
            ),
            "memory_restore": "Odstraněná položka se znovu stane aktivní.",
            "history_continue": "Vznikne nová samostatná relace propojená s původní.",
            "history_delete": (
                "Konverzace zmizí z běžné historie a bude obnovitelná jen po retenční dobu."
            ),
            "history_restore": "Odstraněná konverzace se vrátí do historie.",
        }.get(name, "Dojde ke změně kanonických dat.")

    @staticmethod
    async def _setting(session: AsyncSession, area: str, key: str, fallback: Any) -> Any:
        row = await session.scalar(
            select(ApplicationSetting).where(
                ApplicationSetting.area == area, ApplicationSetting.key == key
            )
        )
        return row.value.get("value", fallback) if row else fallback
