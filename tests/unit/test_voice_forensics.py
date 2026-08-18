import json
from typing import cast

import pytest

from kajovodagmar.diagnostics.voice_forensics import _receive_until


@pytest.mark.asyncio
async def test_receive_until_tolerates_a_transient_receive_timeout() -> None:
    class Socket:
        def __init__(self) -> None:
            self.messages = iter(
                [
                    TimeoutError(),
                    json.dumps({"type": "assistant.audio.end", "payload": {}}),
                ]
            )

        async def recv(self) -> str:
            message = next(self.messages)
            if isinstance(message, TimeoutError):
                raise message
            return cast(str, message)

    events: list[dict[str, object]] = []
    await _receive_until(Socket(), events, "assistant.audio.end")

    assert events == [{"type": "assistant.audio.end", "payload": {}}]
