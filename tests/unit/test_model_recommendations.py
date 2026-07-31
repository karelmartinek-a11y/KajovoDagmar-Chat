from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from kajovodagmar.audit.service import AuditContext
from kajovodagmar.db.models import ModelCatalogEntry, ProviderConfiguration
from kajovodagmar.errors import DomainError
from kajovodagmar.providers.recommendations import ModelRecommendationService


class Rows:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def all(self) -> list[Any]:
        return self.values


class Session:
    def __init__(
        self, provider: Any, entries: list[Any], scalar_values: list[Any]
    ) -> None:
        self.provider = provider
        self.entries = entries
        self.scalar_values = scalar_values
        self.added: list[Any] = []

    async def get(self, *_args: Any, **_kwargs: Any) -> Any:
        return self.provider

    async def scalars(self, _query: Any) -> Rows:
        return Rows(self.entries)

    async def scalar(self, _query: Any) -> Any:
        return self.scalar_values.pop(0) if self.scalar_values else None

    def add(self, value: Any) -> None:
        self.added.append(value)
        if getattr(value, "id", None) is None:
            value.id = uuid4()
        if getattr(value, "version", None) is None:
            value.version = 1

    async def flush(self) -> None:
        return None


def catalog() -> tuple[ProviderConfiguration, list[ModelCatalogEntry]]:
    provider_id = uuid4()
    provider = ProviderConfiguration(
        id=provider_id,
        provider_type="openai",
        display_name="OpenAI",
        base_url="https://api.openai.com/v1",
        enabled=True,
        verification_state="verified",
        catalog_state="ready",
    )
    entries = [
        ModelCatalogEntry(
            id=uuid4(),
            provider_id=provider_id,
            external_id=external_id,
            display_name=external_id,
            role=role,
            capabilities={},
            available=True,
        )
        for role, external_id in (
            ("conversation_model", "gpt-5-mini"),
            ("transcription_model", "gpt-4o-transcribe"),
            ("speech_model", "gpt-4o-mini-tts"),
            ("embedding_model", "text-embedding-3-large"),
            ("summary_model", "gpt-5-mini"),
        )
    ]
    return provider, entries


@pytest.mark.asyncio
async def test_model_options_are_role_specific_and_explain_recommendations() -> None:
    provider, entries = catalog()
    audit = cast(Any, SimpleNamespace(append=AsyncMock()))
    service = ModelRecommendationService(audit)
    result = await service.model_options(
        cast(Any, Session(provider, entries, [None] * 5)), provider.id
    )
    assert set(result["roles"]) == {
        "conversation_model",
        "transcription_model",
        "speech_model",
        "embedding_model",
        "summary_model",
    }
    assert (
        result["roles"]["speech_model"]["options"][0]["external_id"]
        == "gpt-4o-mini-tts"
    )
    assert result["roles"]["speech_model"]["options"][0]["recommended"] is True
    assert result["policy_version"] == "2026-07-31.v1"


@pytest.mark.asyncio
async def test_apply_recommendations_creates_versioned_settings_and_audit() -> None:
    provider, entries = catalog()
    entries = [entry for entry in entries if entry.role != "summary_model"]
    audit = cast(Any, SimpleNamespace(append=AsyncMock()))
    service = ModelRecommendationService(audit)
    session = Session(provider, entries, [None] * 10)
    result = await service.apply_recommended(
        cast(Any, session), provider.id, uuid4(), AuditContext("administrator", uuid4())
    )
    assert len(result["changes"]) == 4
    assert len(session.added) == 8  # four settings plus four history revisions
    audit.append.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_automatic_setting_is_versioned_and_fallback_is_explained() -> (
    None
):
    provider, entries = catalog()
    audit = cast(Any, SimpleNamespace(append=AsyncMock()))
    service = ModelRecommendationService(audit)
    existing = SimpleNamespace(id=uuid4(), value={"value": "old"}, version=4)
    session = Session(provider, entries, [existing])
    await service._set_setting(cast(Any, session), "conversation_model", "new", uuid4())
    assert existing.value == {"value": "new"}
    assert existing.version == 5
    assert service.reason("conversation_model", "gpt-4.1-mini-2026-01-01").startswith(
        "Kompatibilní"
    )


@pytest.mark.asyncio
async def test_model_options_rejects_unknown_provider() -> None:
    audit = cast(Any, SimpleNamespace(append=AsyncMock()))
    service = ModelRecommendationService(audit)
    session = Session(None, [], [])
    with pytest.raises(DomainError, match="Poskytovatel nebyl nalezen"):
        await service.model_options(cast(Any, session), uuid4())
