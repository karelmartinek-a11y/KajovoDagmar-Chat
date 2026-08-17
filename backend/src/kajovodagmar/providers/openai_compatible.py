from __future__ import annotations

import json
from collections.abc import AsyncIterator
from io import BytesIO
from typing import Any
from wave import open as open_wave

import httpx

from kajovodagmar.errors import CapabilityUnavailableError, DomainError
from kajovodagmar.observability.tracing import traced
from kajovodagmar.providers.contracts import (
    AIProvider,
    ChatMessage,
    ChatRequest,
    ChatResult,
    ProviderModel,
    SpeechChunk,
    TranscriptResult,
    enabled_capabilities,
)


class OpenAICompatibleProvider(AIProvider):
    def __init__(self, base_url: str, api_key: str, timeout_seconds: float = 45.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _response_input_message(message: ChatMessage) -> dict[str, Any]:
        """Convert persisted conversation history to Responses API input items."""
        content_type = "output_text" if message.role == "assistant" else "input_text"
        return {
            "role": message.role,
            "content": [{"type": content_type, "text": message.content}],
        }

    @staticmethod
    def _strict_schema_compatible(schema: dict[str, Any]) -> bool:
        """Check the subset accepted by OpenAI strict JSON-schema outputs.

        Application contracts intentionally contain optional fields and free-form
        tool arguments. Those are valid JSON Schema, but are not valid in the
        provider's strict subset. The response is still validated by Pydantic
        after decoding when strict mode is disabled.
        """

        def visit(node: Any) -> bool:
            if isinstance(node, dict):
                if node.get("type") == "object":
                    properties = node.get("properties", {})
                    required = node.get("required", [])
                    if (
                        set(properties) != set(required)
                        or node.get("additionalProperties") is not False
                    ):
                        return False
                return all(visit(value) for value in node.values())
            if isinstance(node, list):
                return all(visit(value) for value in node)
            return True

        return visit(schema)

    @traced("provider.list_models")
    async def list_models(self) -> list[ProviderModel]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
        except httpx.HTTPError as exc:
            raise DomainError(
                "provider_network_error",
                "Katalog poskytovatele není dostupný.",
                503,
                {"capability": "model_catalog", "error": exc.__class__.__name__},
            ) from exc
        self._raise(response, "model_catalog")
        try:
            data = response.json()
        except (ValueError, TypeError) as exc:
            raise DomainError(
                "provider_invalid_response", "Katalog poskytovatele má neplatný formát.", 502
            ) from exc
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise DomainError(
                "provider_invalid_response", "Katalog poskytovatele má neplatný formát.", 502
            )
        models: list[ProviderModel] = []
        for index, item in enumerate(data["data"]):
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise DomainError(
                    "provider_invalid_response",
                    "Katalog obsahuje neplatný model.",
                    502,
                    {"index": index},
                )
            advertised = item.get("capabilities", {})
            if isinstance(advertised, list):
                advertised = {str(value): True for value in advertised}
            if not isinstance(advertised, dict):
                advertised = {}
            models.append(
                ProviderModel(
                    external_id=item["id"],
                    display_name=(
                        item["name"] if isinstance(item.get("name"), str) else item["id"]
                    ),
                    capabilities={str(key): bool(value) for key, value in advertised.items()},
                )
            )
        return models

    @traced("provider.chat")
    async def chat(self, request: ChatRequest) -> ChatResult:
        capabilities = enabled_capabilities(request.capabilities)
        if request.capabilities is not None and "structured_outputs" not in capabilities:
            raise CapabilityUnavailableError(
                "structured_outputs", "Model nemá ověřenou podporu strukturovaných výstupů."
            )
        payload: dict[str, Any] = {
            "model": request.model,
            "input": [self._response_input_message(message) for message in request.messages],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "kajovodagmar_decision",
                    "strict": self._strict_schema_compatible(request.response_schema),
                    "schema": request.response_schema,
                }
            },
        }
        # An empty capability set is the legacy-compatible policy. A populated
        # catalog entry is authoritative and prevents unsupported parameters.
        if not request.capabilities or "temperature" in capabilities:
            payload["temperature"] = request.temperature
        try:
            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/responses", headers=self._headers(), json=payload
                )
        except httpx.HTTPError as exc:
            raise DomainError(
                "provider_network_error",
                "Konverzační poskytovatel není dostupný.",
                503,
                {"capability": "conversation_model", "error": exc.__class__.__name__},
            ) from exc
        self._raise(response, "conversation_model")
        try:
            body = response.json()
        except (ValueError, TypeError) as exc:
            raise DomainError(
                "provider_invalid_response", "Odpověď poskytovatele má neplatný formát.", 502
            ) from exc
        text = self._response_text(body)
        try:
            structured = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DomainError(
                "provider_invalid_structure",
                "Poskytovatel vrátil neplatnou strukturovanou odpověď.",
                502,
            ) from exc
        usage = body.get("usage", {})
        return ChatResult(
            provider_response_id=body.get("id", "unknown"),
            text=structured.get("answer", ""),
            structured=structured,
            input_units=usage.get("input_tokens"),
            output_units=usage.get("output_tokens"),
        )

    @traced("provider.transcribe")
    async def transcribe(self, audio: bytes, *, model: str, language: str) -> TranscriptResult:
        wav = BytesIO()
        with open_wave(wav, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(audio)
        files = {"file": ("turn.wav", wav.getvalue(), "audio/wav")}
        data = {"model": model, "language": language, "response_format": "json"}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/audio/transcriptions", headers=headers, files=files, data=data
            )
        self._raise(response, "transcription")
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            raise DomainError(
                "provider_invalid_response", "Přepisovač vrátil neplatný formát.", 502
            )
        return TranscriptResult(
            text=body["text"],
            language=body.get("language", language),
            provider_response_id=body.get("id", "unknown"),
        )

    async def synthesize(
        self, text: str, *, model: str, voice: str, language: str
    ) -> AsyncIterator[SpeechChunk]:
        payload = {
            "model": model,
            "voice": voice,
            "input": text,
            "response_format": "pcm",
        }
        try:
            async with (
                httpx.AsyncClient(timeout=self.timeout) as client,
                client.stream(
                    "POST", f"{self.base_url}/audio/speech", headers=self._headers(), json=payload
                ) as response,
            ):
                self._raise(response, "speech_synthesis")
                sequence = 0
                async for chunk in response.aiter_bytes(19200):
                    if chunk:
                        yield SpeechChunk(sequence=sequence, pcm16_24000_mono=chunk, final=False)
                        sequence += 1
                yield SpeechChunk(sequence=sequence, pcm16_24000_mono=b"", final=True)
        except httpx.HTTPError as exc:
            raise DomainError(
                "provider_network_error",
                "Hlasový poskytovatel není dostupný.",
                503,
                {"capability": "speech", "error": exc.__class__.__name__},
            ) from exc

    @traced("provider.embed")
    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        payload = {"model": model, "input": texts, "encoding_format": "float"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/embeddings", headers=self._headers(), json=payload
                )
        except httpx.HTTPError as exc:
            raise DomainError(
                "provider_network_error",
                "Embedding poskytovatel není dostupný.",
                503,
                {"capability": "embeddings", "error": exc.__class__.__name__},
            ) from exc
        self._raise(response, "embeddings")
        try:
            body = response.json()
        except (ValueError, TypeError) as exc:
            raise DomainError(
                "provider_invalid_response", "Embedding odpověď má neplatný formát.", 502
            ) from exc
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            raise DomainError(
                "provider_invalid_response", "Embedding odpověď má neplatný formát.", 502
            )
        vectors: list[list[float]] = []
        for index, item in enumerate(data):
            values = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(values, list) or not all(
                isinstance(value, (int, float)) for value in values
            ):
                raise DomainError(
                    "provider_invalid_response",
                    "Embedding odpověď má neplatné hodnoty.",
                    502,
                    {"index": index},
                )
            vectors.append([float(value) for value in values])
        return vectors

    @staticmethod
    def _response_text(body: dict[str, Any]) -> str:
        if isinstance(body.get("output_text"), str):
            return body["output_text"]
        for output in body.get("output", []):
            for content in output.get("content", []):
                if content.get("type") in {"output_text", "text"} and isinstance(
                    content.get("text"), str
                ):
                    return content["text"]
        raise DomainError("provider_empty_response", "Poskytovatel nevrátil textovou odpověď.", 502)

    @staticmethod
    def _raise(response: httpx.Response, capability: str) -> None:
        if response.status_code < 400:
            return
        request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
        error_type: str | None = None
        error_code: str | None = None
        error_param: str | None = None
        try:
            body = response.json()
            error = body.get("error", {}) if isinstance(body, dict) else {}
            if isinstance(error, dict):
                error_type = error.get("type") if isinstance(error.get("type"), str) else None
                error_code = error.get("code") if isinstance(error.get("code"), str) else None
                error_param = error.get("param") if isinstance(error.get("param"), str) else None
        except (ValueError, TypeError):
            pass
        details: dict[str, Any] = {
            "status": response.status_code,
            "capability": capability,
            "endpoint": response.request.url.path if response.request else capability,
        }
        provider_values = (
            ("provider_request_id", request_id),
            ("provider_error_type", error_type),
            ("provider_error_code", error_code),
            ("provider_param", error_param),
        )
        for key, value in provider_values:
            if value:
                details[key] = value
        if response.status_code in {401, 403}:
            raise CapabilityUnavailableError(
                capability,
                "Přístupové údaje poskytovatele nejsou platné nebo nemají potřebné oprávnění.",
            )
        if response.status_code == 404:
            raise CapabilityUnavailableError(
                capability, "Požadovaný model nebo endpoint poskytovatele není dostupný."
            )
        if response.status_code == 429:
            raise DomainError(
                "provider_rate_limited", "Poskytovatel dočasně omezuje požadavky.", 503, details
            )
        if response.status_code in {402, 409} or error_code in {
            "insufficient_quota",
            "billing_hard_limit_reached",
        }:
            raise DomainError(
                "provider_quota",
                "API účet nemá dostupný kredit nebo povolené čerpání.",
                503,
                details,
            )
        if response.status_code == 400 or error_type in {
            "invalid_request_error",
            "invalid_parameter_error",
        }:
            raise DomainError(
                "provider_invalid_parameter",
                "Nastavení požadavku není kompatibilní s vybraným modelem.",
                502,
                details,
            )
        raise DomainError(
            "provider_error",
            "Externí poskytovatel vrátil technickou chybu.",
            502,
            details,
        )
