from __future__ import annotations

from pathlib import Path

import pytest

from kajovodagmar.config import get_settings
from kajovodagmar.db.models import ProviderConfiguration
from kajovodagmar.errors import CapabilityUnavailableError
from kajovodagmar.providers.deterministic import DeterministicProvider
from kajovodagmar.providers.contracts import ChatMessage, ChatRequest
from kajovodagmar.providers.service import ProviderService
from kajovodagmar.main import create_app


def test_create_app_registers_frontend_route_when_static_artifact_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "web" / "dist").mkdir(parents=True)
    app = create_app()
    assert any(getattr(route, "path", None) == "/{path:path}" for route in app.routes)


@pytest.mark.asyncio
async def test_deterministic_provider_has_all_synthetic_capabilities() -> None:
    provider = DeterministicProvider()
    models = await provider.list_models()
    assert {model.external_id for model in models} == {
        "synthetic-acceptance-conversation",
        "synthetic-acceptance-transcription",
        "synthetic-acceptance-speech",
        "synthetic-acceptance-embedding",
    }
    vectors = await provider.embed(
        ["synthetic"], model="synthetic-acceptance-embedding"
    )
    assert len(vectors) == 1
    assert len(vectors[0]) == 3072
    transcription = await provider.transcribe(
        b"synthetic-wav", model="synthetic", language="cs"
    )
    assert "automatický" in transcription.text
    with pytest.raises(ValueError):
        await provider.transcribe(b"", model="synthetic", language="cs")
    chunks = [
        chunk
        async for chunk in provider.synthesize(
            "synthetic speech", model="synthetic", voice="synthetic", language="cs"
        )
    ]
    assert chunks and chunks[0].pcm16_24000_mono
    chat = await provider.chat(
        ChatRequest(
            model="synthetic",
            messages=(ChatMessage(role="user", content="synthetic"),),
            response_schema={},
            temperature=0,
            timeout_seconds=1,
        )
    )
    assert chat.structured["answer"]


@pytest.mark.asyncio
async def test_deterministic_provider_is_not_enabled_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KAJOVODAGMAR_ENVIRONMENT", "production")
    monkeypatch.setenv("KAJOVODAGMAR_ROOT_ENCRYPTION_KEY", "A" * 43)
    monkeypatch.setenv("KAJOVODAGMAR_INITIALIZATION_SECRET_HASH", "0" * 64)
    get_settings.cache_clear()
    assert get_settings().environment == "production"
    service = ProviderService(cipher=None, audit=None)  # type: ignore[arg-type]
    with pytest.raises(CapabilityUnavailableError):
        await service.runtime(  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            ProviderConfiguration(
                provider_type="deterministic",
                display_name="test",
                base_url="http://synthetic.invalid",
            ),
        )
    get_settings.cache_clear()
