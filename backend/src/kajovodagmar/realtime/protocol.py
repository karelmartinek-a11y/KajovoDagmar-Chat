from __future__ import annotations

import struct
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter

PROTOCOL_VERSION = "1.0"
PCM_SAMPLE_RATE = 24000
PCM_CHANNELS = 1
PCM_SAMPLE_BYTES = 2
FRAME_MILLISECONDS = 20
FRAME_SAMPLES = 480
FRAME_BYTES = 960
FRAME_MAGIC = b"KDV1"
FRAME_HEADER_BYTES = 16
FRAME_PACKET_BYTES = FRAME_HEADER_BYTES + FRAME_BYTES
MAX_TURN_SECONDS = 120
MAX_TURN_BYTES = PCM_SAMPLE_RATE * PCM_SAMPLE_BYTES * MAX_TURN_SECONDS


class ClientEnvelope(BaseModel):
    version: Literal["1.0"]
    event_id: UUID
    sequence: int = Field(ge=1)
    type: Literal[
        "session.start",
        "session.resume",
        "microphone.pause",
        "microphone.resume",
        "turn.audio_end",
        "turn.text",
        "assistant.interrupt",
        "session.end",
        "ack",
        "ping",
    ]
    conversation_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    resume_cursor: int | None = None


class ServerEnvelope(BaseModel):
    version: Literal["1.0"] = "1.0"
    event_id: UUID
    sequence: int
    type: str
    conversation_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    ack_for: UUID | None = None


CLIENT_ADAPTER = TypeAdapter(ClientEnvelope)


def validate_audio_frame(data: bytes) -> None:
    if not data or len(data) % FRAME_BYTES != 0:
        raise ValueError(
            f"Zvukový rámec musí obsahovat násobek {FRAME_BYTES} bytů PCM16 24 kHz mono."
        )


def decode_audio_packet(data: bytes) -> tuple[int, float, bytes]:
    if len(data) != FRAME_PACKET_BYTES:
        raise ValueError(f"Binární zvukový paket musí mít přesně {FRAME_PACKET_BYTES} bajtů.")
    magic, sequence, captured_ms = struct.unpack(">4sId", data[:FRAME_HEADER_BYTES])
    if magic != FRAME_MAGIC:
        raise ValueError("Binární zvukový paket nemá platnou verzi KDV1.")
    if sequence < 1 or captured_ms < 0:
        raise ValueError("Pořadí a čas zvukového paketu musí být nezáporné.")
    pcm = data[FRAME_HEADER_BYTES:]
    validate_audio_frame(pcm)
    return sequence, captured_ms, pcm
