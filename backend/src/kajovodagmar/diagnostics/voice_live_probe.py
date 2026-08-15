from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any
from uuid import UUID

from sqlalchemy import select

from kajovodagmar.audit.service import AuditService
from kajovodagmar.config import get_settings
from kajovodagmar.db.models import ApplicationSetting, ModelCatalogEntry, ProviderConfiguration
from kajovodagmar.db.session import Database
from kajovodagmar.providers.contracts import ChatMessage, ChatRequest
from kajovodagmar.providers.service import ProviderService
from kajovodagmar.security.crypto import SecretCipher


async def run_probe() -> dict[str, Any]:  # pragma: no cover - exercised as a container probe
    settings = get_settings()
    db = Database(settings)
    providers = ProviderService(
        SecretCipher(settings.root_encryption_key.get_secret_value()), AuditService()
    )
    result: dict[str, Any] = {
        "status": "pass",
        "commit_sha": os.environ.get("GITHUB_SHA", "unknown"),
        "checks": {},
    }
    try:
        async with db.session() as session:
            selected: dict[str, tuple[ProviderConfiguration, ModelCatalogEntry]] = {}
            for role in (
                "conversation_model",
                "transcription_model",
                "speech_model",
                "embedding_model",
            ):
                setting = await session.scalar(
                    select(ApplicationSetting).where(
                        ApplicationSetting.area == "models", ApplicationSetting.key == role
                    )
                )
                if setting is None or not setting.value.get("value"):
                    raise RuntimeError(f"missing model selection: {role}")
                model = await session.get(ModelCatalogEntry, UUID(str(setting.value["value"])))
                if model is None or not model.available:
                    raise RuntimeError(f"unavailable model selection: {role}")
                provider = await session.get(ProviderConfiguration, model.provider_id)
                if (
                    provider is None
                    or not provider.enabled
                    or provider.verification_state != "verified"
                ):
                    raise RuntimeError(f"unverified provider: {role}")
                selected[role] = (provider, model)
            result["checks"]["selected_models"] = {
                role: {"provider_type": provider.provider_type, "model": model.external_id}
                for role, (provider, model) in selected.items()
            }

            provider, model = selected["conversation_model"]
            runtime = await providers.runtime(session, provider)
            started = time.perf_counter()
            chat = await runtime.chat(
                ChatRequest(
                    model=model.external_id,
                    messages=(
                        ChatMessage(
                            role="user",
                            content="Vrať potvrzení automatického diagnostického testu.",
                        ),
                    ),
                    response_schema={
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                        "additionalProperties": False,
                    },
                    temperature=0.0,
                    timeout_seconds=30.0,
                )
            )
            if not chat.text or not isinstance(chat.structured, dict):
                raise RuntimeError("conversation returned an invalid structured response")
            result["checks"]["conversation"] = {
                "status": "pass",
                "model": model.external_id,
                "provider_request_id": chat.provider_response_id,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }

            provider, model = selected["speech_model"]
            runtime = await providers.runtime(session, provider)
            started = time.perf_counter()
            speech_probe_text = "Automatický test hlasové syntézy."
            pcm_parts: list[bytes] = []
            async for chunk in runtime.synthesize(
                speech_probe_text,
                model=model.external_id,
                voice="alloy",
                language="cs",
            ):
                pcm_parts.append(chunk.pcm16_24000_mono)
            pcm = b"".join(pcm_parts)
            if not pcm:
                raise RuntimeError("speech returned empty PCM")
            result["checks"]["speech"] = {
                "status": "pass",
                "model": model.external_id,
                "pcm_bytes": len(pcm),
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }

            provider, model = selected["transcription_model"]
            runtime = await providers.runtime(session, provider)
            started = time.perf_counter()
            # ``synthesize`` yields raw 24 kHz PCM16.  ``transcribe`` owns
            # WAV framing, so this is a valid end-to-end audio payload rather
            # than a WAV-inside-WAV input or an ambiguous silent recording.
            transcript = await runtime.transcribe(pcm, model=model.external_id, language="cs")
            if not transcript.text.strip():
                raise RuntimeError("transcription returned empty text for synthesized speech")
            result["checks"]["transcription"] = {
                "status": "pass",
                "model": model.external_id,
                "provider_request_id": transcript.provider_response_id,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }

            provider, model = selected["embedding_model"]
            runtime = await providers.runtime(session, provider)
            started = time.perf_counter()
            vectors = await runtime.embed(["syntetický diagnostický text"], model=model.external_id)
            if (
                not vectors
                or not vectors[0]
                or not all(isinstance(value, float) for value in vectors[0])
            ):
                raise RuntimeError("embeddings returned an invalid vector")
            result["checks"]["embeddings"] = {
                "status": "pass",
                "model": model.external_id,
                "dimensions": len(vectors[0]),
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }
    except Exception as exc:
        result["status"] = "fail"
        result["error"] = {"type": exc.__class__.__name__, "message": str(exc)[:240]}
    finally:
        await db.dispose()
    return result


def main() -> int:  # pragma: no cover - exercised by deployment/acceptance command
    report = asyncio.run(run_probe())
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
