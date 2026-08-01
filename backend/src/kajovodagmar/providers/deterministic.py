from __future__ import annotations

from collections.abc import AsyncIterator
from hashlib import sha256

from kajovodagmar.providers.contracts import (
    AIProvider,
    ChatRequest,
    ChatResult,
    ProviderModel,
    SpeechChunk,
    TranscriptResult,
)


class DeterministicProvider(AIProvider):
    """Synthetic provider available only to an isolated test environment."""

    _PREFIX = "synthetic-acceptance-"

    async def list_models(self) -> list[ProviderModel]:
        return [
            ProviderModel(
                self._PREFIX + "conversation",
                "Synthetic conversation",
                frozenset({"responses", "structured_outputs", "chat"}),
            ),
            ProviderModel(
                self._PREFIX + "transcription",
                "Synthetic transcription",
                frozenset({"transcriptions"}),
            ),
            ProviderModel(self._PREFIX + "speech", "Synthetic speech", frozenset({"speech"})),
            ProviderModel(
                self._PREFIX + "embedding", "Synthetic embeddings", frozenset({"embeddings"})
            ),
        ]

    async def chat(self, request: ChatRequest) -> ChatResult:
        return ChatResult(
            provider_response_id="synthetic-chat-1",
            text="Automatický hlasový test proběhl správně.",
            structured={
                "intent": "conversation",
                "result_type": "answer",
                "answer": "Automatický hlasový test proběhl správně.",
                "uncertainty": "none",
                "sources": [],
                "tool_calls": [],
                "memory_proposal": None,
                "requires_confirmation": False,
            },
            input_units=sum(len(message.content) for message in request.messages),
            output_units=1,
        )

    async def transcribe(self, audio: bytes, *, model: str, language: str) -> TranscriptResult:
        if not audio:
            raise ValueError("Synthetic transcription requires non-empty audio.")
        return TranscriptResult(
            text="Toto je automatický test mobilního hlasového chatu.",
            language=language,
            provider_response_id="synthetic-transcription-1",
        )

    async def _speech(
        self, text: str, *, model: str, voice: str, language: str
    ) -> AsyncIterator[SpeechChunk]:
        payload = ("SYNTHETIC_PCM:" + text).encode("utf-8")
        yield SpeechChunk(sequence=0, pcm16_24000_mono=payload, final=True)

    def synthesize(
        self, text: str, *, model: str, voice: str, language: str
    ) -> AsyncIterator[SpeechChunk]:
        return self._speech(text, model=model, voice=voice, language=language)

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = sha256(text.encode("utf-8")).digest()
            vectors.append(
                [((digest[index % len(digest)] / 255.0) * 2.0) - 1.0 for index in range(3072)]
            )
        return vectors
