from __future__ import annotations

import struct

import pytest

from kajovodagmar.realtime.protocol import (
    FRAME_BYTES,
    FRAME_PACKET_BYTES,
    MAX_TURN_BYTES,
    PCM_SAMPLE_RATE,
    decode_audio_packet,
    validate_audio_frame,
)


def test_canonical_audio_contract() -> None:
    assert PCM_SAMPLE_RATE == 24000
    assert FRAME_BYTES == 960
    assert MAX_TURN_BYTES == 5_760_000
    validate_audio_frame(bytes(FRAME_BYTES))
    packet = struct.pack(">4sId", b"KDV1", 7, 125.5) + bytes(FRAME_BYTES)
    sequence, captured_ms, pcm = decode_audio_packet(packet)
    assert (sequence, captured_ms, len(pcm)) == (7, 125.5, FRAME_BYTES)
    assert len(packet) == FRAME_PACKET_BYTES


@pytest.mark.parametrize("size", [0, 1, 959, 961])
def test_invalid_audio_frames_are_rejected(size: int) -> None:
    with pytest.raises(ValueError):
        validate_audio_frame(bytes(size))


@pytest.mark.parametrize(
    "packet",
    [
        b"",
        struct.pack(">4sId", b"BAD!", 1, 1.0) + bytes(FRAME_BYTES),
        struct.pack(">4sId", b"KDV1", 0, 1.0) + bytes(FRAME_BYTES),
        struct.pack(">4sId", b"KDV1", 1, -1.0) + bytes(FRAME_BYTES),
    ],
)
def test_invalid_audio_packets_are_rejected(packet: bytes) -> None:
    with pytest.raises(ValueError):
        decode_audio_packet(packet)
