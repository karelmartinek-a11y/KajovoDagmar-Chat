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
    ChatRequest,
    ChatResult,
    ProviderModel,
    SpeechChunk,
    TranscriptResult,
)


class OpenAICompatibleProvider(AIProvider):
    def __init__(self, base_url: str, api_key: str, timeout_seconds: float = 45.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @traced("provider.list_models")
    async def list_models(self) -> list[ProviderModel]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/models", headers=self._headers())
        self._raise(response, "model_catalog")
        data = response.json()
        return [
            ProviderModel(
                external_id=item["id"],
                display_name=item.get("name", item["id"]),
                capabilities=frozenset(item.get("capabilities", [])),
            )
            for item in data.get("data", [])
        ]

    @traced("provider.chat")
    async def chat(self, request: ChatRequest) -> ChatResult:
        payload = {
            "model": request.model,
            "input": [
                {"role": m.role, "content": [{"type": "input_text", "text": m.content}]}
                for m in request.messages
            ],
            "temperature": request.temperature,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "kajovodagmar_decision",
                    "strict": True,
                    "schema": request.response_schema,
                }
            },
        }
        async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/responses", headers=self._headers(), json=payload
            )
        self._raise(response, "conversation_model")
        body = response.json()
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
            "sample_rate": 24000,
            "language": language,
        }
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

    @traced("provider.embed")
    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        payload = {"model": model, "input": texts, "encoding_format": "float"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/embeddings", headers=self._headers(), json=payload
            )
        self._raise(response, "embeddings")
        return [item["embedding"] for item in response.json().get("data", [])]

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
                "provider_rate_limited", "Poskytovatel dočasně omezuje požadavky.", 503
            )
        raise DomainError(
            "provider_error",
            "Externí poskytovatel vrátil technickou chybu.",
            502,
            {"status": response.status_code},
        )
