from __future__ import annotations

import io
import wave

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kajovodagmar.api.dependencies import RequestIdentity, csrf_guard, db_session
from kajovodagmar.db.models import ApplicationSetting, ModelCatalogEntry, ProviderConfiguration
from kajovodagmar.errors import CapabilityUnavailableError

router = APIRouter(prefix="/voice", tags=["voice"])


class VoicePreviewRequest(BaseModel):
    language: str = Field(default="cs", min_length=2, max_length=16)
    voice: str = Field(default="marin", min_length=2, max_length=32)


@router.post("/preview")
async def preview(
    payload: VoicePreviewRequest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    identity: RequestIdentity = Depends(csrf_guard),
):
    setting = await session.scalar(
        select(ApplicationSetting).where(
            ApplicationSetting.area == "models", ApplicationSetting.key == "speech_model"
        )
    )
    model_id = setting.value.get("value") if setting else None
    model = await session.get(ModelCatalogEntry, model_id) if model_id else None
    if model is None:
        raise CapabilityUnavailableError("voice_preview", "Nejprve vyberte a ověřte model řeči.")
    provider_row = await session.get(ProviderConfiguration, model.provider_id)
    if provider_row is None:
        raise CapabilityUnavailableError("voice_preview", "Poskytovatel hlasu není dostupný.")
    provider = await request.app.state.providers.runtime(session, provider_row)
    text = {
        "cs": "Dobrý den. Toto je krátký náhled vybraného hlasu Dagmar.",
        "en": "Hello. This is a short preview of Dagmar's selected voice.",
        "de": "Guten Tag. Dies ist eine kurze Vorschau der ausgewählten Stimme.",
    }.get(payload.language, "Dobrý den. Toto je krátký náhled vybraného hlasu Dagmar.")
    pcm = bytearray()
    async for chunk in provider.synthesize(
        text, model=model.external_id, voice=payload.voice, language=payload.language
    ):
        pcm.extend(chunk.pcm16_24000_mono)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(bytes(pcm))
    return Response(
        output.getvalue(), media_type="audio/wav", headers={"Cache-Control": "no-store"}
    )
