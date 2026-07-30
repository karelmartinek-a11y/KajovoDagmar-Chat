from __future__ import annotations

import time
import pytest
from kajovodagmar.security.crypto import token_digest
from kajovodagmar.realtime.protocol import validate_audio_frame, FRAME_BYTES

pytestmark = pytest.mark.performance


def test_protocol_validation_budget() -> None:
    frame = bytes(FRAME_BYTES)
    started = time.perf_counter()
    for _ in range(10000):
        validate_audio_frame(frame)
    assert time.perf_counter() - started < 0.25


def test_token_digest_budget() -> None:
    started = time.perf_counter()
    for index in range(10000):
        token_digest(str(index), "session")
    assert time.perf_counter() - started < 0.25
