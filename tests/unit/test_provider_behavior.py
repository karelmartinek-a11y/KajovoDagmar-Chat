from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from kajovodagmar.audit.service import AuditContext
from kajovodagmar.db.models import EncryptedSecret, ProviderConfiguration
from kajovodagmar.errors import (
    CapabilityUnavailableError,
    ConflictError,
    DomainError,
    NotFoundError,
)
from kajovodagmar.providers.contracts import ChatMessage, ChatRequest, ProviderModel
from kajovodagmar.providers.openai_compatible import OpenAICompatibleProvider
from kajovodagmar.providers.service import ProviderService
from kajovodagmar.security.crypto import SecretCipher
from kajovodagmar.types import utc_now

ROOT_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"


class Rows:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def all(self) -> list[Any]:
        return self.values


class Session:
    def __init__(
        self,
        *,
        gets: list[Any] | None = None,
        scalars: list[Any] | None = None,
    ) -> None:
        self.gets = gets or []
        self.scalar_values = scalars or []
        self.added: list[Any] = []

    async def get(self, *_args: Any, **_kwargs: Any) -> Any:
        return self.gets.pop(0) if self.gets else None

    async def scalar(self, _query: Any) -> Any:
        return self.scalar_values.pop(0) if self.scalar_values else None

    def add(self, value: Any) -> None:
        self.added.append(value)
        if getattr(value, "id", None) is None:
            value.id = uuid4()

    async def flush(self) -> None:
        return None


def provider_service() -> Any:
    return ProviderService(
        SecretCipher(ROOT_KEY),
        cast(Any, SimpleNamespace(append=AsyncMock())),
    )


@pytest.mark.asyncio
async def test_provider_configuration_save_verify_and_runtime() -> None:
    service = provider_service()
    account_id = uuid4()
    context = AuditContext("administrator", account_id)
    session = Session()
    row = await service.save(
        cast(Any, session),
        provider_id=None,
        provider_type="openai_compatible",
        display_name="Primární",
        base_url="https://provider.invalid/v1",
        api_key="secret-token",
        expected_version=0,
        context=context,
    )
    assert row.display_name == "Primární"
    assert row.secret_id is not None
    assert session.added[1].masked_hint == "••••oken"

    row.version = 2
    with pytest.raises(ConflictError):
        await service.save(
            cast(Any, Session(gets=[row])),
            provider_id=row.id,
            provider_type=row.provider_type,
            display_name="Změna",
            base_url=row.base_url,
            api_key=None,
            expected_version=1,
            context=context,
        )
    updated = await service.save(
        cast(Any, Session(gets=[row])),
        provider_id=row.id,
        provider_type=row.provider_type,
        display_name="Změna",
        base_url="https://new.invalid/v1",
        api_key=None,
        expected_version=2,
        context=context,
    )
    assert updated.version == 3
    assert updated.verification_state == "not_verified"

    with pytest.raises(NotFoundError):
        await service.verify(cast(Any, Session(gets=[None])), uuid4(), context)
    model_a = ProviderModel("a", "Model A", frozenset({"chat"}))
    model_b = ProviderModel("b", "Model B", frozenset({"audio"}))
    existing = SimpleNamespace(
        display_name="Old", capabilities={}, available=False, last_seen_at=None
    )
    service.runtime = AsyncMock(
        return_value=SimpleNamespace(
            list_models=AsyncMock(return_value=[model_a, model_b])
        )
    )
    verified_session = Session(gets=[row], scalars=[None, existing])
    catalog = await service.verify(cast(Any, verified_session), row.id, context)
    assert row.enabled is True
    assert row.verification_state == "verified"
    assert len(catalog) == 2
    assert existing.display_name == "Model A"

    runtime_service = provider_service()
    no_secret = ProviderConfiguration(
        id=uuid4(),
        provider_type="openai_compatible",
        display_name="No key",
        base_url="https://provider.invalid/v1",
    )
    with pytest.raises(CapabilityUnavailableError):
        await runtime_service.runtime(cast(Any, Session()), no_secret)
    secret_id = uuid4()
    no_secret.secret_id = secret_id
    with pytest.raises(CapabilityUnavailableError):
        await runtime_service.runtime(cast(Any, Session(gets=[None])), no_secret)
    revoked = EncryptedSecret(
        id=secret_id,
        purpose="provider",
        ciphertext="ciphertext",
        key_version=1,
        masked_hint="••••oked",
        revoked_at=utc_now(),
    )
    with pytest.raises(CapabilityUnavailableError):
        await runtime_service.runtime(cast(Any, Session(gets=[revoked])), no_secret)
    encrypted = runtime_service.cipher.encrypt(
        "api-value", purpose="provider_api_key", record_id=str(no_secret.id)
    )
    secret = EncryptedSecret(
        id=secret_id,
        purpose="provider",
        ciphertext=encrypted.to_json(),
        key_version=1,
        masked_hint="••••alue",
    )
    no_secret.provider_type = "unsupported"
    with pytest.raises(CapabilityUnavailableError):
        await runtime_service.runtime(cast(Any, Session(gets=[secret])), no_secret)
    no_secret.provider_type = "openai_compatible"
    runtime = await runtime_service.runtime(
        cast(Any, Session(gets=[secret])), no_secret
    )
    assert runtime.api_key == "api-value"
    assert runtime_service._mask("abc") == "••••"


@pytest.mark.asyncio
async def test_provider_key_replacement_revokes_previous_secret() -> None:
    service = provider_service()
    row = ProviderConfiguration(
        id=uuid4(),
        provider_type="openai",
        display_name="OpenAI",
        base_url="https://provider.invalid/v1",
        secret_id=uuid4(),
    )
    row.version = 1
    old_secret = EncryptedSecret(
        id=row.secret_id,
        purpose="provider",
        ciphertext="ciphertext",
        key_version=1,
        masked_hint="••••old",
    )
    await service.save(
        cast(Any, Session(gets=[row, old_secret])),
        provider_id=row.id,
        provider_type="openai",
        display_name="OpenAI",
        base_url=row.base_url,
        api_key="new-secret-token",
        expected_version=1,
        context=AuditContext("administrator", uuid4()),
    )
    assert old_secret.revoked_at is not None


@pytest.mark.asyncio
async def test_provider_key_replacement_tolerates_missing_previous_secret() -> None:
    service = provider_service()
    row = ProviderConfiguration(
        id=uuid4(),
        provider_type="openai",
        display_name="OpenAI",
        base_url="https://provider.invalid/v1",
        secret_id=uuid4(),
    )
    row.version = 1
    await service.save(
        cast(Any, Session(gets=[row, None])),
        provider_id=row.id,
        provider_type="openai",
        display_name="OpenAI",
        base_url=row.base_url,
        api_key="replacement-token",
        expected_version=1,
        context=AuditContext("administrator", uuid4()),
    )


@pytest.mark.asyncio
async def test_provider_verification_reuses_existing_role_entry() -> None:
    service = provider_service()
    row = ProviderConfiguration(
        id=uuid4(),
        provider_type="openai",
        display_name="OpenAI",
        base_url="https://provider.invalid/v1",
    )
    previous = SimpleNamespace(available=True)

    class CatalogSession(Session):
        async def scalars(self, _query: Any) -> Rows:
            return Rows([previous])

    service.runtime = AsyncMock(
        return_value=SimpleNamespace(
            list_models=AsyncMock(
                return_value=[ProviderModel("whisper-1", "Whisper", frozenset())]
            )
        )
    )
    session = CatalogSession(gets=[row], scalars=[previous])
    service_result = await service.verify(
        cast(Any, session), row.id, AuditContext("administrator", uuid4())
    )
    assert previous.available is True
    assert service_result[0] is previous


@pytest.mark.asyncio
async def test_provider_verification_keeps_catalog_on_failure_and_rejects_empty() -> (
    None
):
    service = provider_service()
    row = ProviderConfiguration(
        id=uuid4(),
        provider_type="openai",
        display_name="OpenAI",
        base_url="https://provider.invalid/v1",
    )
    context = AuditContext("administrator", uuid4())
    service.runtime = AsyncMock(
        return_value=SimpleNamespace(
            list_models=AsyncMock(side_effect=RuntimeError("temporary failure"))
        )
    )
    with pytest.raises(RuntimeError):
        await service.verify(cast(Any, Session(gets=[row])), row.id, context)
    assert row.catalog_state == "stale_error"

    service.runtime = AsyncMock(
        return_value=SimpleNamespace(list_models=AsyncMock(return_value=[]))
    )
    with pytest.raises(DomainError, match="prázdnou nabídku"):
        await service.verify(cast(Any, Session(gets=[row])), row.id, context)
    assert row.catalog_state == "empty"


@pytest.mark.asyncio
async def test_openai_compatible_provider_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "model-1", "name": "Model One", "capabilities": ["chat"]}
                    ]
                },
            )
        if request.url.path.endswith("/responses"):
            body = json.loads(request.content)
            assert body["text"]["format"]["strict"] is True
            assert body["input"] == [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": "Pravidla"}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "První dotaz"}],
                },
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "První odpověď"}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Druhý dotaz"}],
                },
            ]
            return httpx.Response(
                200,
                json={
                    "id": "response-1",
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps({"answer": "Dobrý den"}),
                                }
                            ]
                        }
                    ],
                    "usage": {"input_tokens": 4, "output_tokens": 2},
                },
            )
        if request.url.path.endswith("/audio/transcriptions"):
            assert b"RIFF" in request.content
            assert b"WAVE" in request.content
            return httpx.Response(
                200, json={"id": "stt-1", "text": "Přepis", "language": "cs"}
            )
        if request.url.path.endswith("/audio/speech"):
            return httpx.Response(200, content=b"pcm-audio")
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def client(*_args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    provider = OpenAICompatibleProvider("https://provider.invalid/v1/", "key")
    assert provider.base_url.endswith("/v1")
    assert provider._headers()["Authorization"] == "Bearer key"
    models = await provider.list_models()
    assert models[0].external_id == "model-1"
    request = ChatRequest(
        model="model-1",
        messages=(
            ChatMessage("system", "Pravidla"),
            ChatMessage("user", "První dotaz"),
            ChatMessage("assistant", "První odpověď"),
            ChatMessage("user", "Druhý dotaz"),
        ),
        response_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
        temperature=0.1,
        timeout_seconds=5,
    )
    chat = await provider.chat(request)
    assert chat.text == "Dobrý den"
    assert chat.input_units == 4
    transcript = await provider.transcribe(b"pcm", model="stt", language="cs")
    assert transcript.text == "Přepis"
    chunks = [
        chunk
        async for chunk in provider.synthesize(
            "Text", model="tts", voice="voice", language="cs"
        )
    ]
    assert b"".join(chunk.pcm16_24000_mono for chunk in chunks) == b"pcm-audio"
    assert chunks[-1].final is True
    assert await provider.embed(["text"], model="embedding") == [[0.1, 0.2]]


def test_provider_response_validation_branches() -> None:
    response = lambda status: httpx.Response(  # noqa: E731
        status, request=httpx.Request("GET", "https://provider.invalid")
    )
    OpenAICompatibleProvider._raise(response(200), "chat")
    for status in (401, 403, 404):
        with pytest.raises(CapabilityUnavailableError):
            OpenAICompatibleProvider._raise(response(status), "chat")
    with pytest.raises(DomainError, match="omezuje"):
        OpenAICompatibleProvider._raise(response(429), "chat")
    with pytest.raises(DomainError, match="technickou"):
        OpenAICompatibleProvider._raise(response(500), "chat")
    invalid = httpx.Response(
        400,
        json={
            "error": {
                "type": "invalid_request_error",
                "code": "invalid_parameter",
                "param": "temperature",
            }
        },
        headers={"x-request-id": "req-safe-1"},
        request=httpx.Request("POST", "https://provider.invalid/v1/responses"),
    )
    with pytest.raises(DomainError) as invalid_error:
        OpenAICompatibleProvider._raise(invalid, "conversation_model")
    assert invalid_error.value.code == "provider_invalid_parameter"
    assert invalid_error.value.details == {
        "status": 400,
        "capability": "conversation_model",
        "endpoint": "/v1/responses",
        "provider_request_id": "req-safe-1",
        "provider_error_type": "invalid_request_error",
        "provider_error_code": "invalid_parameter",
        "provider_param": "temperature",
    }
    for status in (402, 409):
        with pytest.raises(DomainError, match="kredit"):
            OpenAICompatibleProvider._raise(
                httpx.Response(
                    status, request=httpx.Request("POST", "https://provider.invalid")
                ),
                "speech_synthesis",
            )
    assert OpenAICompatibleProvider._response_text({"output_text": "text"}) == "text"
    assert (
        OpenAICompatibleProvider._response_text(
            {"output": [{"content": [{"type": "text", "text": "nested"}]}]}
        )
        == "nested"
    )
    with pytest.raises(DomainError, match="nevrátil text"):
        OpenAICompatibleProvider._response_text({})


def test_provider_detects_non_strict_json_schema() -> None:
    assert OpenAICompatibleProvider._strict_schema_compatible(
        {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        }
    )
    assert not OpenAICompatibleProvider._strict_schema_compatible(
        {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": [],
            "additionalProperties": True,
        }
    )
