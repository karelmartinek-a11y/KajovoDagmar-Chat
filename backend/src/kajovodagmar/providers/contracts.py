from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ProviderModel:
    external_id: str
    display_name: str
    capabilities: frozenset[str]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ChatRequest:
    model: str
    messages: tuple[ChatMessage, ...]
    response_schema: dict[str, Any]
    temperature: float
    timeout_seconds: float
    capabilities: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ChatResult:
    provider_response_id: str
    text: str
    structured: dict[str, Any]
    input_units: int | None
    output_units: int | None


@dataclass(frozen=True, slots=True)
class TranscriptResult:
    text: str
    language: str
    provider_response_id: str


@dataclass(frozen=True, slots=True)
class SpeechChunk:
    sequence: int
    pcm16_24000_mono: bytes
    final: bool


class AIProvider(Protocol):
    async def list_models(self) -> list[ProviderModel]: ...
    async def chat(self, request: ChatRequest) -> ChatResult: ...
    async def transcribe(self, audio: bytes, *, model: str, language: str) -> TranscriptResult: ...
    def synthesize(
        self, text: str, *, model: str, voice: str, language: str
    ) -> AsyncIterator[SpeechChunk]: ...
    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]: ...
