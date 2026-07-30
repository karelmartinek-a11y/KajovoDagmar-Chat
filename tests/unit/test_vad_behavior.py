from __future__ import annotations

import struct

import pytest

from kajovodagmar.realtime.protocol import FRAME_SAMPLES
from kajovodagmar.realtime.vad import VoiceActivityDetector


def pcm(value: int) -> bytes:
    return struct.pack(f"<{FRAME_SAMPLES}h", *([value] * FRAME_SAMPLES))


def test_vad_requires_stable_voice_and_ends_after_configured_silence() -> None:
    detector = VoiceActivityDetector(
        threshold=500, start_frames=3, endpoint_silence_ms=60
    )
    assert detector.process(pcm(0)).level == 0
    assert detector.process(pcm(1000)).started is False
    assert detector.process(pcm(1000)).started is False
    started = detector.process(pcm(1000))
    assert started.started is True
    assert detector.active is True
    assert detector.process(pcm(0)).ended is False
    assert detector.process(pcm(0)).ended is False
    ended = detector.process(pcm(0))
    assert ended.ended is True
    assert detector.active is False


def test_vad_reset_and_invalid_configuration() -> None:
    detector = VoiceActivityDetector()
    detector.process(pcm(1000))
    detector.reset()
    assert detector.active is False
    with pytest.raises(ValueError):
        VoiceActivityDetector(threshold=0)
