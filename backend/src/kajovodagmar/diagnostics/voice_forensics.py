from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import struct
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import websockets
from websockets.typing import Subprotocol

from kajovodagmar.realtime.protocol import FRAME_MAGIC, FRAME_SAMPLES


def _event(event_type: str, sequence: int, payload: dict[str, Any] | None = None) -> str:
    return json.dumps(
        {
            "version": "1.0",
            "event_id": str(uuid4()),
            "sequence": sequence,
            "type": event_type,
            "payload": payload or {},
        },
        separators=(",", ":"),
    )


def _pcm_frame(frame_number: int, voiced: bool) -> bytes:
    samples = []
    for index in range(FRAME_SAMPLES):
        value = (
            int(8500 * math.sin(2 * math.pi * 440 * (frame_number * FRAME_SAMPLES + index) / 24000))
            if voiced
            else 0
        )
        samples.append(value)
    pcm = struct.pack("<480h", *samples)
    return struct.pack(">4sId", FRAME_MAGIC, frame_number, frame_number * 20.0) + pcm


async def run() -> dict[str, Any]:
    started = time.perf_counter()
    base_url = os.environ.get("VOICE_FORENSICS_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://") + "/api/v1/realtime"
    key_file = Path(
        os.environ.get(
            "KAJOVODAGMAR_VOICE_SERVICE_API_KEY_FILE",
            "/run/secrets/voice-service-api-key",
        )
    )
    key = key_file.read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError("voice service key is empty")
    report: dict[str, Any] = {
        "status": "fail",
        "checks": {},
        "started_at": time.time(),
    }
    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30.0) as client:
        ticket_started = time.perf_counter()
        response = await client.post("/api/v1/realtime/ticket")
        response.raise_for_status()
        ticket = response.json()["ticket"]
        report["checks"]["ticket"] = {
            "status": "pass",
            "duration_ms": round((time.perf_counter() - ticket_started) * 1000),
        }
    server_events: list[dict[str, Any]] = []
    audio_parts: list[bytes] = []
    async with websockets.connect(
        f"{ws_url}?ticket={ticket}",
        subprotocols=[Subprotocol("kajovodagmar.realtime.v1")],
        open_timeout=20,
    ) as socket:
        await _receive_until(socket, server_events, "connection.ready")
        await socket.send(_event("session.start", 1, {"language": "cs"}))
        await _receive_until(socket, server_events, "session.started")
        input_pcm = bytearray()
        for frame in range(1, 36):
            packet = _pcm_frame(frame, True)
            input_pcm.extend(packet[16:])
            await socket.send(packet)
        turn_event_id = str(uuid4())
        await socket.send(
            json.dumps(
                {
                    "version": "1.0",
                    "event_id": turn_event_id,
                    "sequence": 2,
                    "type": "turn.audio_end",
                    "payload": {},
                },
                separators=(",", ":"),
            )
        )
        await _receive_until(socket, server_events, "assistant.audio.end", audio_parts)
        await socket.send(
            _event(
                "turn.text",
                3,
                {"text": "Potvrď druhý tah automatického hlasového testu."},
            )
        )
        await _receive_until(socket, server_events, "assistant.audio.end", audio_parts)
        if sum(event.get("type") == "assistant.text" for event in server_events) != 2:
            raise RuntimeError("realtime conversation did not complete two assistant turns")
        await socket.send(_event("session.end", 4, {}))
        await _receive_until(socket, server_events, "session.ended", audio_parts)
    report["checks"]["realtime"] = {
        "status": "pass",
        "event_types": [event["type"] for event in server_events],
        "input_pcm_sha256": hashlib.sha256(input_pcm).hexdigest(),
        "output_audio_sha256": hashlib.sha256(b"".join(audio_parts)).hexdigest(),
        "output_audio_bytes": sum(len(part) for part in audio_parts),
        "turns": 2,
    }
    report["status"] = "pass"
    report["duration_ms"] = round((time.perf_counter() - started) * 1000)
    return report


async def _receive_until(
    socket: Any,
    events: list[dict[str, Any]],
    expected: str,
    audio_parts: list[bytes] | None = None,
) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            message = await asyncio.wait_for(socket.recv(), timeout=15)
        except TimeoutError:
            continue
        if isinstance(message, bytes):
            if audio_parts is not None:
                audio_parts.append(message)
            continue
        event = json.loads(message)
        events.append(event)
        if event.get("type") == "error":
            raise RuntimeError(event.get("payload", {}).get("message", "realtime error"))
        if event.get("type") == expected:
            return
    raise TimeoutError(f"realtime event {expected!r} was not received")


def main() -> int:
    try:
        print(json.dumps(asyncio.run(run()), ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "fail",
                    "error": {"type": type(exc).__name__, "message": str(exc)[:240]},
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
