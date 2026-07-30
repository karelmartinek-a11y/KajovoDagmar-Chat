from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from kajovodagmar.audit.service import AuditContext
from kajovodagmar.conversations.schemas import ConversationStart, UserTurn
from kajovodagmar.db.models import ApplicationSetting, ModelCatalogEntry, ProviderConfiguration
from kajovodagmar.errors import DomainError
from kajovodagmar.observability.metrics import REALTIME_EVENTS, WEBSOCKET_CONNECTIONS
from kajovodagmar.observability.tracing import traced
from kajovodagmar.realtime.protocol import (
    CLIENT_ADAPTER,
    MAX_TURN_BYTES,
    PCM_SAMPLE_BYTES,
    PCM_SAMPLE_RATE,
    ServerEnvelope,
    decode_audio_packet,
)
from kajovodagmar.realtime.tickets import consume_ticket
from kajovodagmar.realtime.vad import VoiceActivityDetector

RESUME_WINDOW_SECONDS = 30
PARTIAL_TRANSCRIPT_INTERVAL_BYTES = PCM_SAMPLE_RATE * PCM_SAMPLE_BYTES
FLOW_CONTROL_ACK_FRAMES = 10


@dataclass(slots=True)
class ConnectionState:
    account_id: UUID
    sequence: int = 0
    last_client_sequence: int = 0
    conversation_id: UUID | None = None
    paused: bool = False
    audio: bytearray = field(default_factory=bytearray)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    assistant_task: asyncio.Task[None] | None = None
    partial_task: asyncio.Task[None] | None = None
    partial_text: str = ""
    partial_at_bytes: int = 0
    generation: int = 1
    last_audio_sequence: int = 0
    last_audio_capture_ms: float = -1.0
    turn_finalizing: bool = False
    vad: VoiceActivityDetector = field(default_factory=VoiceActivityDetector)
    expiration_task: asyncio.Task[None] | None = None

    def event(
        self, event_type: str, payload: dict[str, Any], ack_for: UUID | None = None
    ) -> ServerEnvelope:
        self.sequence += 1
        return ServerEnvelope(
            event_id=uuid4(),
            sequence=self.sequence,
            type=event_type,
            conversation_id=self.conversation_id,
            payload=payload,
            ack_for=ack_for,
        )


async def emit(
    websocket: WebSocket,
    state: ConnectionState,
    event_type: str,
    payload: dict[str, Any],
    ack_for: UUID | None = None,
) -> None:
    async with state.send_lock:
        event = state.event(event_type, payload, ack_for)
        await websocket.send_text(event.model_dump_json())
        REALTIME_EVENTS.labels("out", event_type, "sent").inc()


async def send_audio(websocket: WebSocket, state: ConnectionState, data: bytes) -> None:
    async with state.send_lock:
        await websocket.send_bytes(data)


@traced("realtime.session")
async def handle_realtime(websocket: WebSocket, app: Any) -> None:
    ticket = websocket.query_params.get("ticket")
    if not ticket:
        await websocket.close(code=4401, reason="Chybí realtime vstupenka.")
        return
    async with app.state.database.session() as db:
        try:
            account_id = await consume_ticket(db, ticket)
        except DomainError:
            await websocket.close(code=4401, reason="Realtime vstupenka není platná.")
            return
    sessions: dict[UUID, ConnectionState] = getattr(app.state, "realtime_sessions", {})
    app.state.realtime_sessions = sessions
    requested_session = websocket.query_params.get("session_id")
    state = ConnectionState(account_id)
    resume_available = False
    if requested_session:
        with suppress(ValueError):
            session_id = UUID(requested_session)
            suspended = sessions.pop(session_id, None)
            requested_generation = int(websocket.query_params.get("generation", "0"))
            if (
                suspended is not None
                and suspended.account_id == account_id
                and requested_generation == suspended.generation + 1
            ):
                if suspended.expiration_task:
                    suspended.expiration_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await suspended.expiration_task
                state = suspended
                state.generation = requested_generation
                state.send_lock = asyncio.Lock()
                state.expiration_task = None
                state.paused = True
                resume_available = True
            elif suspended is not None and suspended.conversation_id:
                sessions[suspended.conversation_id] = suspended
    await websocket.accept(subprotocol="kajovodagmar.realtime.v1")
    WEBSOCKET_CONNECTIONS.inc()
    try:
        await emit(
            websocket,
            state,
            "connection.ready",
            {
                "audio": {
                    "format": "pcm_s16le",
                    "sample_rate": 24000,
                    "channels": 1,
                    "frame_ms": 20,
                },
                "resume_supported": True,
                "resume_available": resume_available,
                "generation": state.generation,
                "last_client_sequence": state.last_client_sequence,
            },
        )
        while True:
            message = await websocket.receive()
            if message.get("bytes") is not None:
                await receive_audio(websocket, app, state, message["bytes"])
                continue
            raw = message.get("text")
            if raw is None:
                continue
            try:
                envelope = CLIENT_ADAPTER.validate_json(raw)
            except Exception:
                await emit(
                    websocket,
                    state,
                    "error",
                    {"code": "invalid_event", "message": "Událost neodpovídá realtime kontraktu."},
                )
                continue
            if envelope.sequence <= state.last_client_sequence:
                await emit(websocket, state, "ack", {"duplicate": True}, envelope.event_id)
                continue
            if envelope.sequence != state.last_client_sequence + 1:
                await emit(
                    websocket,
                    state,
                    "resync.required",
                    {
                        "expected_sequence": state.last_client_sequence + 1,
                        "received_sequence": envelope.sequence,
                    },
                    envelope.event_id,
                )
                continue
            state.last_client_sequence = envelope.sequence
            REALTIME_EVENTS.labels("in", envelope.type, "accepted").inc()
            if envelope.type == "ping":
                await emit(websocket, state, "pong", {}, envelope.event_id)
            elif envelope.type == "session.start":
                if resume_available:
                    await emit(
                        websocket,
                        state,
                        "error",
                        {
                            "code": "resume_required",
                            "message": "Rozpracovaná relace vyžaduje bezpečné obnovení.",
                        },
                        envelope.event_id,
                    )
                    continue
                await start_session(websocket, app, state, envelope)
            elif envelope.type == "session.resume":
                if not resume_available or not state.conversation_id:
                    await emit(
                        websocket,
                        state,
                        "resync.required",
                        {"reason": "resume_unavailable"},
                        envelope.event_id,
                    )
                    continue
                cursor = envelope.resume_cursor
                if cursor is None or cursor > state.sequence:
                    await emit(
                        websocket,
                        state,
                        "resync.required",
                        {"reason": "invalid_resume_cursor", "server_sequence": state.sequence},
                        envelope.event_id,
                    )
                    continue
                incomplete = bool(state.audio)
                state.audio.clear()
                state.vad.reset()
                state.turn_finalizing = False
                state.partial_at_bytes = 0
                state.paused = False
                await emit(
                    websocket,
                    state,
                    "session.resumed",
                    {
                        "state": "listening",
                        "generation": state.generation,
                        "partial_transcript": state.partial_text,
                        "input_incomplete": incomplete,
                        "last_audio_sequence": state.last_audio_sequence,
                    },
                    envelope.event_id,
                )
                if incomplete:
                    await emit(
                        websocket,
                        state,
                        "turn.incomplete",
                        {"message": "Přerušená hlasová replika nebyla finalizována; zopakujte ji."},
                    )
                resume_available = False
            elif envelope.type == "microphone.pause":
                state.paused = True
                state.audio.clear()
                state.vad.reset()
                await emit(
                    websocket, state, "state.changed", {"state": "paused"}, envelope.event_id
                )
            elif envelope.type == "microphone.resume":
                state.paused = False
                await emit(
                    websocket, state, "state.changed", {"state": "listening"}, envelope.event_id
                )
            elif envelope.type == "turn.text":
                if not state.conversation_id:
                    await emit(
                        websocket,
                        state,
                        "error",
                        {"code": "session_required", "message": "Nejprve zahajte rozhovor."},
                        envelope.event_id,
                    )
                    continue
                await replace_assistant_task(
                    state,
                    process_text_turn(
                        websocket,
                        app,
                        state,
                        str(envelope.payload.get("text", "")),
                        str(envelope.event_id),
                        envelope.event_id,
                    ),
                )
            elif envelope.type == "turn.audio_end":
                if state.turn_finalizing:
                    await emit(
                        websocket,
                        state,
                        "ack",
                        {"duplicate": True, "turn_state": "finalizing"},
                        envelope.event_id,
                    )
                    continue
                if not state.conversation_id or not state.audio:
                    await emit(
                        websocket,
                        state,
                        "error",
                        {"code": "audio_empty", "message": "Nebyl přijat žádný zvuk."},
                        envelope.event_id,
                    )
                    continue
                await finalize_audio_turn(
                    websocket,
                    app,
                    state,
                    str(envelope.payload.get("language", "cs")),
                    envelope.event_id,
                    "manual",
                )
            elif envelope.type == "assistant.interrupt":
                await cancel_assistant_task(state)
                await emit(
                    websocket,
                    state,
                    "assistant.interrupted",
                    {"state": "listening"},
                    envelope.event_id,
                )
            elif envelope.type == "session.end":
                await cancel_assistant_task(state)
                if state.conversation_id:
                    async with app.state.database.session() as db:
                        await app.state.conversations.end(
                            db,
                            state.account_id,
                            state.conversation_id,
                            "user_ended",
                            AuditContext(
                                "administrator",
                                state.account_id,
                                correlation_id=str(envelope.event_id),
                            ),
                        )
                await emit(websocket, state, "session.ended", {"state": "ended"}, envelope.event_id)
                state.conversation_id = None
                state.audio.clear()
                state.vad.reset()
            else:
                await emit(websocket, state, "ack", {}, envelope.event_id)
    except WebSocketDisconnect:
        await cancel_assistant_task(state)
        await cancel_partial_task(state)
        if state.conversation_id:
            state.paused = True
            sessions[state.conversation_id] = state
            state.expiration_task = asyncio.create_task(expire_suspended_session(app, state))
    finally:
        WEBSOCKET_CONNECTIONS.dec()


async def receive_audio(
    websocket: WebSocket, app: Any, state: ConnectionState, data: bytes
) -> None:
    if state.paused or state.conversation_id is None:
        await emit(
            websocket,
            state,
            "error",
            {"code": "audio_not_accepted", "message": "Mikrofon není v aktivním stavu."},
        )
        return
    try:
        frame_sequence, captured_ms, pcm = decode_audio_packet(data)
    except ValueError as exc:
        await emit(websocket, state, "error", {"code": "invalid_audio_frame", "message": str(exc)})
        return
    if frame_sequence <= state.last_audio_sequence:
        await emit(
            websocket,
            state,
            "audio.ack",
            {"frame_sequence": frame_sequence, "duplicate": True},
        )
        return
    if (
        frame_sequence != state.last_audio_sequence + 1
        or captured_ms <= state.last_audio_capture_ms
    ):
        state.paused = True
        await emit(
            websocket,
            state,
            "flow_control",
            {
                "level": "hard",
                "reason": "audio_sequence_gap",
                "expected_frame_sequence": state.last_audio_sequence + 1,
            },
        )
        return
    if len(state.audio) + len(pcm) > MAX_TURN_BYTES:
        state.last_audio_sequence = frame_sequence
        state.last_audio_capture_ms = captured_ms
        await emit(
            websocket,
            state,
            "turn.ended",
            {
                "frame_sequence": frame_sequence,
                "reason": "maximum_duration",
                "message": "Hlasová replika dosáhla maximální délky 120 sekund.",
            },
        )
        await finalize_audio_turn(websocket, app, state, "cs", uuid4(), "maximum_duration")
        return
    state.last_audio_sequence = frame_sequence
    state.last_audio_capture_ms = captured_ms
    state.audio.extend(pcm)
    REALTIME_EVENTS.labels("in", "audio", "accepted").inc()
    activity = state.vad.process(pcm)
    if activity.started:
        await emit(
            websocket,
            state,
            "turn.started",
            {"frame_sequence": frame_sequence, "level": round(activity.level, 2)},
        )
    if (
        state.vad.active
        and len(state.audio) - state.partial_at_bytes >= PARTIAL_TRANSCRIPT_INTERVAL_BYTES
        and (state.partial_task is None or state.partial_task.done())
    ):
        state.partial_at_bytes = len(state.audio)
        state.partial_task = asyncio.create_task(
            emit_partial_transcript(websocket, app, state, bytes(state.audio), "cs")
        )
    if frame_sequence % FLOW_CONTROL_ACK_FRAMES == 0:
        await emit(
            websocket,
            state,
            "audio.ack",
            {"frame_sequence": frame_sequence, "captured_ms": captured_ms},
        )
    if activity.ended:
        await emit(
            websocket,
            state,
            "turn.ended",
            {"frame_sequence": frame_sequence, "reason": "server_vad"},
        )
        await finalize_audio_turn(websocket, app, state, "cs", uuid4(), "server_vad")


async def emit_partial_transcript(
    websocket: WebSocket,
    app: Any,
    state: ConnectionState,
    audio: bytes,
    language: str,
) -> None:
    try:
        text = (await transcribe(app, audio, language)).strip()
        if text and text != state.partial_text and not state.turn_finalizing:
            state.partial_text = text
            await emit(websocket, state, "transcript.partial", {"text": text})
    except (DomainError, TimeoutError):
        REALTIME_EVENTS.labels("out", "transcript.partial", "unavailable").inc()


async def cancel_partial_task(state: ConnectionState) -> None:
    task = state.partial_task
    if task and not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    state.partial_task = None


async def finalize_audio_turn(
    websocket: WebSocket,
    app: Any,
    state: ConnectionState,
    language: str,
    ack_for: UUID,
    reason: str,
) -> None:
    if state.turn_finalizing or not state.audio:
        return
    state.turn_finalizing = True
    await cancel_partial_task(state)
    audio = bytes(state.audio)
    state.audio.clear()
    state.vad.reset()
    state.partial_at_bytes = 0
    await replace_assistant_task(
        state,
        process_audio_turn(websocket, app, state, audio, language, ack_for),
    )
    REALTIME_EVENTS.labels("in", f"turn_end_{reason}", "accepted").inc()


async def expire_suspended_session(app: Any, state: ConnectionState) -> None:
    try:
        await asyncio.sleep(RESUME_WINDOW_SECONDS)
        conversation_id = state.conversation_id
        sessions: dict[UUID, ConnectionState] = app.state.realtime_sessions
        if not conversation_id or sessions.get(conversation_id) is not state:
            return
        sessions.pop(conversation_id, None)
        async with app.state.database.session() as db:
            await app.state.conversations.end(
                db,
                state.account_id,
                conversation_id,
                "connection_lost",
                AuditContext("administrator", state.account_id),
            )
        state.conversation_id = None
        state.audio.clear()
        state.vad.reset()
    except asyncio.CancelledError:
        raise


async def start_session(
    websocket: WebSocket, app: Any, state: ConnectionState, envelope: Any
) -> None:
    continuation = envelope.payload.get("continuation_of_id")
    async with app.state.database.session() as db:
        setting_value = getattr(app.state, "setting_value", None)
        endpoint_silence_ms = (
            int(await setting_value(db, "voice", "endpoint_silence_ms", 900))
            if setting_value is not None
            else 900
        )
        state.vad = VoiceActivityDetector(endpoint_silence_ms=endpoint_silence_ms)
        row = await app.state.conversations.start(
            db,
            state.account_id,
            ConversationStart(
                input_mode="voice",
                language=str(envelope.payload.get("language", "cs")),
                continuation_of_id=UUID(str(continuation)) if continuation else None,
            ),
            AuditContext("administrator", state.account_id, correlation_id=str(envelope.event_id)),
        )
        state.conversation_id = row.id
    await emit(websocket, state, "session.started", {"state": "listening"}, envelope.event_id)


async def replace_assistant_task(state: ConnectionState, coroutine: Any) -> None:
    await cancel_assistant_task(state)
    state.assistant_task = asyncio.create_task(coroutine)


async def cancel_assistant_task(state: ConnectionState) -> None:
    task = state.assistant_task
    if task and not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    state.assistant_task = None


async def process_audio_turn(
    websocket: WebSocket,
    app: Any,
    state: ConnectionState,
    audio: bytes,
    language: str,
    ack_for: UUID,
) -> None:
    try:
        await emit(websocket, state, "state.changed", {"state": "processing"}, ack_for)
        transcript = await transcribe(app, audio, language)
        await emit(websocket, state, "transcript.final", {"text": transcript}, ack_for)
        await process_text_turn(
            websocket,
            app,
            state,
            transcript,
            str(ack_for),
            ack_for,
            input_mode="voice",
            state_already_processing=True,
        )
    except asyncio.CancelledError:
        raise
    except DomainError as exc:
        await emit(websocket, state, "error", {"code": exc.code, "message": exc.message}, ack_for)
    finally:
        state.turn_finalizing = False
        state.partial_text = ""


async def process_text_turn(
    websocket: WebSocket,
    app: Any,
    state: ConnectionState,
    text: str,
    idempotency_key: str,
    ack_for: UUID,
    input_mode: Literal["voice", "text"] = "text",
    state_already_processing: bool = False,
) -> None:
    if not text.strip():
        await emit(
            websocket,
            state,
            "error",
            {"code": "empty_turn", "message": "Replika je prázdná."},
            ack_for,
        )
        return
    if not state_already_processing:
        await emit(websocket, state, "state.changed", {"state": "processing"}, ack_for)
    try:
        async with app.state.database.session() as db:
            message = await app.state.conversations.add_user_turn(
                db,
                state.account_id,
                state.conversation_id,
                UserTurn(
                    idempotency_key=idempotency_key,
                    content=text,
                    input_mode=input_mode,
                    language="cs",
                ),
                AuditContext("administrator", state.account_id, correlation_id=idempotency_key),
            )
            result = await app.state.orchestration.answer(
                db,
                state.account_id,
                state.conversation_id,
                message.id,
                AuditContext("administrator", state.account_id, correlation_id=idempotency_key),
            )
        await emit(
            websocket,
            state,
            "assistant.text",
            {
                "message_id": str(result.message.id),
                "run_id": str(result.run_id),
                "text": result.message.content,
                "intent": result.decision.intent,
                "sources": [source.model_dump() for source in result.decision.sources],
                "memory_proposal": result.decision.memory_proposal.model_dump()
                if result.decision.memory_proposal
                else None,
                "actions": [
                    {
                        "id": str(action.id),
                        "name": action.name,
                        "state": action.state,
                        "preview": action.preview,
                        "expires_at": action.expires_at.isoformat() if action.expires_at else None,
                        "version": action.version,
                    }
                    for action in result.actions
                ],
            },
            ack_for,
        )
        await synthesize(websocket, app, state, result.message.content, "cs")
    except asyncio.CancelledError:
        await emit(websocket, state, "assistant.interrupted", {"state": "listening"}, ack_for)
        raise
    except DomainError as exc:
        await emit(websocket, state, "error", {"code": exc.code, "message": exc.message}, ack_for)
    finally:
        if state.conversation_id:
            await emit(websocket, state, "state.changed", {"state": "listening"})


async def transcribe(app: Any, audio: bytes, language: str) -> str:
    async with app.state.database.session() as db:
        model, provider_row = await resolve_model(db, "transcription_model")
        provider = await app.state.providers.runtime(db, provider_row)
        result = await provider.transcribe(audio, model=model.external_id, language=language)
        return result.text


async def synthesize(
    websocket: WebSocket, app: Any, state: ConnectionState, text: str, language: str
) -> None:
    try:
        async with app.state.database.session() as db:
            model, provider_row = await resolve_model(db, "speech_model")
            voice_setting = await db.scalar(
                select(ApplicationSetting).where(
                    ApplicationSetting.area == "voice", ApplicationSetting.key == "voice_id"
                )
            )
            if not voice_setting or not voice_setting.value.get("value"):
                raise DomainError(
                    "capability_unavailable", "V Nastavení není vybrán hlas asistentky.", 503
                )
            provider = await app.state.providers.runtime(db, provider_row)
            voice = str(voice_setting.value["value"])
            await emit(
                websocket,
                state,
                "assistant.audio.start",
                {"format": "pcm_s16le", "sample_rate": 24000, "channels": 1},
            )
            async for chunk in provider.synthesize(
                text, model=model.external_id, voice=voice, language=language
            ):
                if chunk.pcm16_24000_mono:
                    await send_audio(websocket, state, chunk.pcm16_24000_mono)
            await emit(websocket, state, "assistant.audio.end", {"completed": True})
    except DomainError as exc:
        await emit(
            websocket,
            state,
            "assistant.audio.error",
            {"code": exc.code, "message": exc.message, "text_available": True},
        )


async def resolve_model(
    db: Any, setting_key: str
) -> tuple[ModelCatalogEntry, ProviderConfiguration]:
    setting = await db.scalar(
        select(ApplicationSetting).where(
            ApplicationSetting.area == "models", ApplicationSetting.key == setting_key
        )
    )
    if not setting or not setting.value.get("value"):
        raise DomainError(
            "capability_unavailable", f"V Nastavení není vybrána modelová role {setting_key}.", 503
        )
    try:
        model_id = UUID(str(setting.value["value"]))
    except ValueError as exc:
        raise DomainError(
            "capability_unavailable", "Uložený identifikátor modelu není platný.", 503
        ) from exc
    model = await db.get(ModelCatalogEntry, model_id)
    if not model or not model.available:
        raise DomainError("capability_unavailable", "Vybraný model není dostupný.", 503)
    provider_row = await db.get(ProviderConfiguration, model.provider_id)
    if (
        not provider_row
        or not provider_row.enabled
        or provider_row.verification_state != "verified"
    ):
        raise DomainError(
            "capability_unavailable", "Poskytovatel vybraného modelu není ověřený a aktivní.", 503
        )
    return model, provider_row
