from __future__ import annotations

import asyncio
import json
import struct
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from kajovodagmar.errors import DomainError
from kajovodagmar.realtime import websocket as realtime
from kajovodagmar.realtime.tickets import consume_ticket, issue_ticket
from kajovodagmar.types import utc_now
from starlette.websockets import WebSocketDisconnect


def audio_packet(sequence: int, captured_ms: float, pcm: bytes | None = None) -> bytes:
    return struct.pack(">4sId", b"KDV1", sequence, captured_ms) + (pcm or b"\0" * 960)


class SessionContext:
    def __init__(self, session: Any) -> None:
        self.session = session

    async def __aenter__(self) -> Any:
        return self.session

    async def __aexit__(self, *_args: Any) -> None:
        return None


class FakeDatabase:
    def __init__(self, session: Any) -> None:
        self.value = session

    def session(self) -> SessionContext:
        return SessionContext(self.value)


def fake_app(session: Any) -> Any:
    return SimpleNamespace(
        state=SimpleNamespace(
            database=FakeDatabase(session),
            conversations=SimpleNamespace(
                start=AsyncMock(),
                end=AsyncMock(),
                add_user_turn=AsyncMock(),
            ),
            orchestration=SimpleNamespace(answer=AsyncMock()),
            providers=SimpleNamespace(runtime=AsyncMock()),
        )
    )


@pytest.mark.asyncio
async def test_emit_audio_validation_and_size_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = SimpleNamespace(send_text=AsyncMock(), send_bytes=AsyncMock())
    state = realtime.ConnectionState(uuid4(), conversation_id=uuid4())
    ack = uuid4()
    await realtime.emit(cast(Any, websocket), state, "test.event", {"ok": True}, ack)
    assert state.sequence == 1
    assert '"ack_for"' in websocket.send_text.await_args.args[0]
    await realtime.send_audio(cast(Any, websocket), state, b"pcm")
    websocket.send_bytes.assert_awaited_once_with(b"pcm")

    state.paused = True
    await realtime.receive_audio(
        cast(Any, websocket), SimpleNamespace(), state, audio_packet(1, 1)
    )
    assert state.audio == b""
    assert websocket.send_text.await_count == 1
    state.paused = False
    await realtime.receive_audio(cast(Any, websocket), SimpleNamespace(), state, b"bad")
    assert state.audio == b""
    state.audio.extend(b"\0" * realtime.MAX_TURN_BYTES)
    finalizer = AsyncMock()
    monkeypatch.setattr(realtime, "finalize_audio_turn", finalizer)
    await realtime.receive_audio(
        cast(Any, websocket), SimpleNamespace(), state, audio_packet(1, 1)
    )
    finalizer.assert_awaited_once()
    state = realtime.ConnectionState(uuid4(), conversation_id=uuid4())
    await realtime.receive_audio(
        cast(Any, websocket), SimpleNamespace(), state, audio_packet(1, 2)
    )
    assert len(state.audio) == 960


@pytest.mark.asyncio
async def test_start_session_and_assistant_task_lifecycle() -> None:
    row = SimpleNamespace(id=uuid4())
    session = SimpleNamespace()
    app = fake_app(session)
    app.state.conversations.start.return_value = row
    websocket = SimpleNamespace(send_text=AsyncMock())
    state = realtime.ConnectionState(uuid4())
    envelope = SimpleNamespace(
        payload={"language": "cs", "continuation_of_id": str(uuid4())},
        event_id=uuid4(),
    )
    await realtime.start_session(cast(Any, websocket), app, state, envelope)
    assert state.conversation_id == row.id
    app.state.conversations.start.assert_awaited_once()

    reached = asyncio.Event()

    async def running() -> None:
        reached.set()
        await asyncio.sleep(60)

    await realtime.replace_assistant_task(state, running())
    await reached.wait()
    assert state.assistant_task is not None
    await realtime.cancel_assistant_task(state)
    assert state.assistant_task is None
    await realtime.cancel_assistant_task(state)


@pytest.mark.asyncio
async def test_text_turn_empty_success_domain_error_and_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = SimpleNamespace(send_text=AsyncMock(), send_bytes=AsyncMock())
    state = realtime.ConnectionState(uuid4(), conversation_id=uuid4())
    app = fake_app(SimpleNamespace())
    ack = uuid4()
    await realtime.process_text_turn(
        cast(Any, websocket), app, state, "   ", "idem", ack
    )

    message = SimpleNamespace(id=uuid4())
    decision = SimpleNamespace(intent="answer", sources=[], memory_proposal=None)
    result = SimpleNamespace(
        message=SimpleNamespace(id=uuid4(), content="Doložená odpověď"),
        run_id=uuid4(),
        decision=decision,
        actions=[],
    )
    app.state.conversations.add_user_turn.return_value = message
    app.state.orchestration.answer.return_value = result
    synthesis = AsyncMock()
    monkeypatch.setattr(realtime, "synthesize", synthesis)
    await realtime.process_text_turn(
        cast(Any, websocket), app, state, "Dotaz", "idempotency-key-0001", ack
    )
    synthesis.assert_awaited_once()
    emitted = [json.loads(call.args[0]) for call in websocket.send_text.await_args_list]
    assert any(
        event["type"] == "transcript.final"
        and event["payload"] == {"text": "Dotaz", "message_id": str(message.id)}
        for event in emitted
    )

    app.state.orchestration.answer.side_effect = DomainError(
        "provider", "Není model.", 503
    )
    await realtime.process_text_turn(
        cast(Any, websocket), app, state, "Další dotaz", "idempotency-key-0002", ack
    )

    app.state.orchestration.answer.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await realtime.process_text_turn(
            cast(Any, websocket), app, state, "Přerušit", "idempotency-key-0003", ack
        )


@pytest.mark.asyncio
async def test_audio_turn_success_and_domain_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = SimpleNamespace(send_text=AsyncMock())
    state = realtime.ConnectionState(uuid4(), conversation_id=uuid4())
    ack = uuid4()
    transcription = AsyncMock(return_value="Přepsaná věta")
    processing = AsyncMock()
    monkeypatch.setattr(realtime, "transcribe", transcription)
    monkeypatch.setattr(realtime, "process_text_turn", processing)
    await realtime.process_audio_turn(
        cast(Any, websocket), SimpleNamespace(), state, b"audio", "cs", ack
    )
    processing.assert_awaited_once()

    transcription.side_effect = DomainError("stt", "Přepis není dostupný.", 503)
    await realtime.process_audio_turn(
        cast(Any, websocket), SimpleNamespace(), state, b"audio", "cs", ack
    )


class ModelSession:
    def __init__(self, scalar: Any, gets: list[Any]) -> None:
        self.scalar_value = scalar
        self.gets = gets

    async def scalar(self, _query: Any) -> Any:
        return self.scalar_value

    async def get(self, *_args: Any) -> Any:
        return self.gets.pop(0)


@pytest.mark.asyncio
async def test_resolve_model_all_validation_branches() -> None:
    with pytest.raises(DomainError):
        await realtime.resolve_model(ModelSession(None, []), "speech_model")
    with pytest.raises(DomainError):
        await realtime.resolve_model(
            ModelSession(SimpleNamespace(value={"value": "not-a-uuid"}), []),
            "speech_model",
        )
    model_id = uuid4()
    setting = SimpleNamespace(value={"value": str(model_id)})
    with pytest.raises(DomainError):
        await realtime.resolve_model(ModelSession(setting, [None]), "speech_model")
    unavailable = SimpleNamespace(available=False)
    with pytest.raises(DomainError):
        await realtime.resolve_model(
            ModelSession(setting, [unavailable]), "speech_model"
        )
    model = SimpleNamespace(available=True, provider_id=uuid4())
    with pytest.raises(DomainError):
        await realtime.resolve_model(
            ModelSession(setting, [model, None]), "speech_model"
        )
    disabled = SimpleNamespace(enabled=False, verification_state="verified")
    with pytest.raises(DomainError):
        await realtime.resolve_model(
            ModelSession(setting, [model, disabled]), "speech_model"
        )
    provider = SimpleNamespace(enabled=True, verification_state="verified")
    assert await realtime.resolve_model(
        ModelSession(setting, [model, provider]), "speech_model"
    ) == (model, provider)


@pytest.mark.asyncio
async def test_transcribe_and_synthesize_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = SimpleNamespace(external_id="model")
    provider_row = SimpleNamespace()
    session = SimpleNamespace(scalar=AsyncMock())
    app = fake_app(session)
    provider = SimpleNamespace(
        transcribe=AsyncMock(return_value=SimpleNamespace(text="Výsledek"))
    )
    app.state.providers.runtime.return_value = provider
    monkeypatch.setattr(
        realtime, "resolve_model", AsyncMock(return_value=(model, provider_row))
    )
    assert await realtime.transcribe(app, b"audio", "cs") == "Výsledek"

    websocket = SimpleNamespace(send_text=AsyncMock(), send_bytes=AsyncMock())
    state = realtime.ConnectionState(uuid4(), conversation_id=uuid4())
    session.scalar.return_value = None
    await realtime.synthesize(cast(Any, websocket), app, state, "Text", "cs")

    session.scalar.return_value = SimpleNamespace(value={"value": "voice"})

    async def chunks():
        yield SimpleNamespace(pcm16_24000_mono=b"first")
        yield SimpleNamespace(pcm16_24000_mono=b"")
        yield SimpleNamespace(pcm16_24000_mono=b"second")

    provider.synthesize = lambda *_args, **_kwargs: chunks()
    await realtime.synthesize(cast(Any, websocket), app, state, "Text", "cs")
    assert websocket.send_bytes.await_count == 2


class TicketSession:
    def __init__(self, scalar: Any = None) -> None:
        self.scalar_value = scalar
        self.added: list[Any] = []
        self.executed = 0

    async def execute(self, _query: Any) -> None:
        self.executed += 1

    async def scalar(self, _query: Any) -> Any:
        return self.scalar_value

    def add(self, value: Any) -> None:
        self.added.append(value)


@pytest.mark.asyncio
async def test_realtime_ticket_single_use_and_expiration() -> None:
    account_id = uuid4()
    session = TicketSession()
    token, expires = await issue_ticket(cast(Any, session), account_id)
    assert token
    assert expires
    assert session.executed == 1
    assert session.added[0].account_id == account_id
    with pytest.raises(DomainError):
        await consume_ticket(cast(Any, TicketSession()), token)
    expired = SimpleNamespace(
        account_id=account_id,
        used_at=None,
        invalidated_at=None,
        expires_at=utc_now(),
    )
    with pytest.raises(DomainError):
        await consume_ticket(cast(Any, TicketSession(expired)), token)
    valid = SimpleNamespace(
        account_id=account_id,
        used_at=None,
        invalidated_at=None,
        expires_at=utc_now() + timedelta(minutes=1),
    )
    assert await consume_ticket(cast(Any, TicketSession(valid)), token) == account_id
    assert valid.used_at is not None


def envelope(
    sequence: int, event_type: str, payload: dict[str, Any] | None = None
) -> str:
    return (
        '{"version":"1.0","event_id":"'
        + str(uuid4())
        + f'","sequence":{sequence},"type":"{event_type}","payload":'
        + json.dumps(payload or {})
        + "}"
    )


def resume_envelope(sequence: int, cursor: int) -> str:
    return json.dumps(
        {
            "version": "1.0",
            "event_id": str(uuid4()),
            "sequence": sequence,
            "type": "session.resume",
            "payload": {"generation": 2},
            "resume_cursor": cursor,
        }
    )


@pytest.mark.asyncio
async def test_vad_partial_transcript_audio_ack_and_automatic_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = SimpleNamespace(send_text=AsyncMock())
    state = realtime.ConnectionState(
        uuid4(),
        conversation_id=uuid4(),
        vad=realtime.VoiceActivityDetector(
            threshold=500, start_frames=3, endpoint_silence_ms=60
        ),
    )
    app = SimpleNamespace()
    partial = AsyncMock(return_value="Průběžný přepis")
    finalizer = AsyncMock()
    monkeypatch.setattr(realtime, "transcribe", partial)
    monkeypatch.setattr(realtime, "finalize_audio_turn", finalizer)
    monkeypatch.setattr(realtime, "PARTIAL_TRANSCRIPT_INTERVAL_BYTES", 960)
    loud = struct.pack("<480h", *([1000] * 480))
    for sequence in range(1, 4):
        await realtime.receive_audio(
            cast(Any, websocket),
            app,
            state,
            audio_packet(sequence, float(sequence), loud),
        )
    await asyncio.sleep(0)
    for sequence in range(4, 7):
        await realtime.receive_audio(
            cast(Any, websocket),
            app,
            state,
            audio_packet(sequence, float(sequence)),
        )
    await asyncio.sleep(0)
    sent = "\n".join(call.args[0] for call in websocket.send_text.await_args_list)
    assert "turn.started" in sent
    assert "transcript.partial" in sent
    assert "turn.ended" in sent
    finalizer.assert_awaited_once()
    assert finalizer.await_args_list[0].args[-1] == "server_vad"


@pytest.mark.asyncio
async def test_audio_packet_gap_duplicate_and_real_finalizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = SimpleNamespace(send_text=AsyncMock())
    state = realtime.ConnectionState(uuid4(), conversation_id=uuid4())
    await realtime.receive_audio(
        cast(Any, websocket), SimpleNamespace(), state, audio_packet(2, 2)
    )
    assert state.paused is True
    state.paused = False
    await realtime.receive_audio(
        cast(Any, websocket), SimpleNamespace(), state, audio_packet(1, 1)
    )
    await realtime.receive_audio(
        cast(Any, websocket), SimpleNamespace(), state, audio_packet(1, 1)
    )
    assert "duplicate" in websocket.send_text.await_args.args[0]

    state.audio.extend(b"turn")
    processor = AsyncMock()
    monkeypatch.setattr(realtime, "process_audio_turn", processor)
    await realtime.finalize_audio_turn(
        cast(Any, websocket), SimpleNamespace(), state, "cs", uuid4(), "manual"
    )
    assert state.turn_finalizing is True
    assert state.audio == b""
    assert state.assistant_task is not None
    await state.assistant_task
    processor.assert_awaited_once()
    await realtime.finalize_audio_turn(
        cast(Any, websocket), SimpleNamespace(), state, "cs", uuid4(), "manual"
    )


@pytest.mark.asyncio
async def test_realtime_handler_protocol_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = SimpleNamespace(
        query_params={},
        close=AsyncMock(),
    )
    await realtime.handle_realtime(cast(Any, missing), SimpleNamespace())
    missing.close.assert_awaited_once_with(
        code=4401, reason="Chybí realtime vstupenka."
    )

    account_id = uuid4()
    app = fake_app(SimpleNamespace())
    invalid = SimpleNamespace(
        query_params={"ticket": "bad"},
        close=AsyncMock(),
    )
    monkeypatch.setattr(
        realtime,
        "consume_ticket",
        AsyncMock(side_effect=DomainError("ticket", "invalid", 401)),
    )
    await realtime.handle_realtime(cast(Any, invalid), app)
    invalid.close.assert_awaited_once_with(
        code=4401, reason="Realtime vstupenka není platná."
    )

    monkeypatch.setattr(realtime, "consume_ticket", AsyncMock(return_value=account_id))
    conversation_id = uuid4()
    app.state.conversations.start.return_value = SimpleNamespace(id=conversation_id)

    async def quick_text(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def quick_audio(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(realtime, "process_text_turn", quick_text)
    monkeypatch.setattr(realtime, "process_audio_turn", quick_audio)
    messages = [
        {"bytes": b"\0" * 960},
        {},
        {"text": "invalid"},
        {"text": envelope(1, "ping")},
        {"text": envelope(1, "ping")},
        {"text": envelope(3, "ping")},
        {"text": envelope(2, "session.start", {"language": "cs"})},
        {"text": envelope(3, "microphone.pause")},
        {"text": envelope(4, "microphone.resume")},
        {"text": envelope(5, "turn.text", {"text": "Dotaz"})},
        {"text": envelope(6, "turn.audio_end")},
        {"bytes": b"\0" * 960},
        {"text": envelope(7, "turn.audio_end", {"language": "cs"})},
        {"text": envelope(8, "assistant.interrupt")},
        {"text": envelope(9, "ack")},
        {"text": envelope(10, "session.end")},
        WebSocketDisconnect(),
    ]
    websocket = SimpleNamespace(
        query_params={"ticket": "good"},
        accept=AsyncMock(),
        close=AsyncMock(),
        send_text=AsyncMock(),
        send_bytes=AsyncMock(),
        receive=AsyncMock(side_effect=messages),
    )
    await realtime.handle_realtime(cast(Any, websocket), app)
    websocket.accept.assert_awaited_once_with(subprotocol="kajovodagmar.realtime.v1")
    sent = "\n".join(call.args[0] for call in websocket.send_text.await_args_list)
    for event_type in (
        "connection.ready",
        "invalid_event",
        "duplicate",
        "resync.required",
        "session.started",
        "paused",
        "listening",
        "audio_empty",
        "assistant.interrupted",
        "session.ended",
    ):
        assert event_type in sent
    app.state.conversations.end.assert_awaited_once()


@pytest.mark.asyncio
async def test_realtime_handler_resumes_suspended_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id, conversation_id = uuid4(), uuid4()
    app = fake_app(SimpleNamespace())
    state = realtime.ConnectionState(
        account_id,
        sequence=4,
        last_client_sequence=1,
        conversation_id=conversation_id,
        audio=bytearray(b"incomplete"),
    )
    state.expiration_task = asyncio.create_task(asyncio.sleep(60))
    app.state.realtime_sessions = {conversation_id: state}
    monkeypatch.setattr(realtime, "consume_ticket", AsyncMock(return_value=account_id))
    websocket = SimpleNamespace(
        query_params={
            "ticket": "good",
            "session_id": str(conversation_id),
            "generation": "2",
        },
        accept=AsyncMock(),
        send_text=AsyncMock(),
        receive=AsyncMock(
            side_effect=[
                {"text": resume_envelope(2, 4)},
                {"text": envelope(3, "session.end")},
                WebSocketDisconnect(),
            ]
        ),
    )
    await realtime.handle_realtime(cast(Any, websocket), app)
    sent = "\n".join(call.args[0] for call in websocket.send_text.await_args_list)
    assert '"resume_available":true' in sent
    assert "session.resumed" in sent
    assert "turn.incomplete" in sent
    assert state.generation == 1
    assert state.audio == b""


@pytest.mark.asyncio
async def test_realtime_disconnect_closes_active_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id, conversation_id = uuid4(), uuid4()
    app = fake_app(SimpleNamespace())
    app.state.conversations.start.return_value = SimpleNamespace(id=conversation_id)
    monkeypatch.setattr(realtime, "consume_ticket", AsyncMock(return_value=account_id))
    websocket = SimpleNamespace(
        query_params={"ticket": "good"},
        accept=AsyncMock(),
        send_text=AsyncMock(),
        receive=AsyncMock(
            side_effect=[
                {"text": envelope(1, "session.start")},
                WebSocketDisconnect(),
            ]
        ),
    )
    monkeypatch.setattr(realtime, "RESUME_WINDOW_SECONDS", 0)
    await realtime.handle_realtime(cast(Any, websocket), app)
    suspended = app.state.realtime_sessions[conversation_id]
    await suspended.expiration_task
    assert app.state.conversations.end.await_args.args[3] == "connection_lost"
