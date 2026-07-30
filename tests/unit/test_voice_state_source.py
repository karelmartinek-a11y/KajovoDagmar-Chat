from pathlib import Path


def test_frontend_state_machine_contains_all_canonical_states() -> None:
    source = Path("web/src/audio/voiceState.ts").read_text(encoding="utf-8")
    for state in [
        "ready",
        "connecting",
        "listening",
        "processing",
        "responding",
        "paused",
        "reconnecting",
        "error",
        "ended",
    ]:
        assert f"'{state}'" in source
