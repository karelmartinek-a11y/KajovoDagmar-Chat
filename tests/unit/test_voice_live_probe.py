from types import SimpleNamespace
from uuid import uuid4

import pytest

from kajovodagmar.diagnostics import voice_live_probe
from kajovodagmar.providers.contracts import ChatResult, SpeechChunk, TranscriptResult


@pytest.mark.asyncio
async def test_live_probe_transcribes_raw_pcm_from_speech_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_id = uuid4()
    models = {
        role: SimpleNamespace(
            id=uuid4(), provider_id=provider_id, external_id=role, available=True
        )
        for role in (
            "conversation_model",
            "transcription_model",
            "speech_model",
            "embedding_model",
        )
    }
    provider = SimpleNamespace(
        enabled=True, verification_state="verified", provider_type="openai"
    )
    pcm = b"\x01\x00" * 24_000

    class FakeSession:
        def __init__(self) -> None:
            self.roles = iter(models)

        async def scalar(self, _query: object) -> object:
            role = next(self.roles)
            return SimpleNamespace(value={"value": str(models[role].id)})

        async def get(self, model_type: object, identifier: object) -> object:
            if model_type is voice_live_probe.ModelCatalogEntry:
                return next(
                    model for model in models.values() if model.id == identifier
                )
            return provider

    class SessionContext:
        async def __aenter__(self) -> FakeSession:
            return FakeSession()

        async def __aexit__(self, *_args: object) -> None:
            return None

    class ProbeDatabase:
        def __init__(self, _settings: object) -> None:
            self.settings = _settings

        def session(self) -> SessionContext:
            return SessionContext()

        async def dispose(self) -> None:
            return None

    class ProbeRuntime:
        async def chat(self, _request: object) -> ChatResult:
            return ChatResult("chat-1", "hotovo", {"answer": "hotovo"}, None, None)

        async def transcribe(
            self, audio: bytes, *, model: str, language: str
        ) -> TranscriptResult:
            assert audio == pcm
            assert not audio.startswith(b"RIFF")
            assert model == "transcription_model"
            assert language == "cs"
            return TranscriptResult(
                "Automatický test hlasové syntézy.", language, "stt-1"
            )

        async def embed(self, _texts: list[str], *, model: str) -> list[list[float]]:
            assert model == "embedding_model"
            return [[0.1] * 1536]

        async def synthesize(self, text: str, *, model: str, voice: str, language: str):
            assert text == "Automatický test hlasové syntézy."
            assert model == "speech_model"
            assert voice == "alloy"
            assert language == "cs"
            yield SpeechChunk(sequence=0, pcm16_24000_mono=pcm, final=True)

    class ProbeProviders:
        def __init__(self, *_args: object) -> None:
            self.runtime_instance = ProbeRuntime()

        async def runtime(self, _session: object, _provider: object) -> ProbeRuntime:
            return self.runtime_instance

    monkeypatch.setattr(
        voice_live_probe,
        "get_settings",
        lambda: SimpleNamespace(
            root_encryption_key=SimpleNamespace(get_secret_value=lambda: "A" * 43)
        ),
    )
    monkeypatch.setattr(voice_live_probe, "Database", ProbeDatabase)
    monkeypatch.setattr(voice_live_probe, "ProviderService", ProbeProviders)
    monkeypatch.setattr(voice_live_probe, "SecretCipher", lambda _key: object())

    result = await voice_live_probe.run_probe()

    assert result["status"] == "pass"
    assert set(result["checks"]) == {
        "selected_models",
        "conversation",
        "speech",
        "transcription",
        "embeddings",
    }
