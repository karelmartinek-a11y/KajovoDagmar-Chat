from kajovodagmar.diagnostics.voice_live_probe import _pcm16_silence


def test_voice_live_probe_uses_raw_pcm16_not_nested_wav() -> None:
    payload = _pcm16_silence()

    assert payload == b"\x00\x00" * 24_000
    assert len(payload) == 48_000
    assert not payload.startswith(b"RIFF")
