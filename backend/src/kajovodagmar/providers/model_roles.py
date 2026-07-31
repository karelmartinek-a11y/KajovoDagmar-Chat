from __future__ import annotations

import re
from dataclasses import dataclass

MODEL_RECOMMENDATION_POLICY_VERSION = "2026-07-31.v1"

ROLE_ORDER = (
    "conversation_model",
    "transcription_model",
    "speech_model",
    "embedding_model",
    "summary_model",
)

ROLE_TITLES = {
    "conversation_model": "Mozek rozhovoru",
    "transcription_model": "Sluch – převod řeči na text",
    "speech_model": "Řeč – převod textu na hlas",
    "embedding_model": "Paměť – hledání souvisejících informací",
    "summary_model": "Archivář – názvy a shrnutí rozhovorů",
}

ROLE_DESCRIPTIONS = {
    "conversation_model": (
        "Rozumí tomu, co říkáte nebo píšete, rozhoduje, co má Dagmar odpovědět, "
        "a připravuje obsah odpovědi. Ovlivňuje porozumění kontextu a kvalitu "
        "odpovědi, ale nevytváří zvuk ani nepřepisuje mikrofon."
    ),
    "transcription_model": (
        "Poslouchá zvuk z mikrofonu a převádí jej na napsanou větu. Ovlivňuje "
        "hlavně správné rozpoznání češtiny, jmen, čísel a méně zřetelné řeči, "
        "ale nerozhoduje, jak Dagmar odpoví."
    ),
    "speech_model": (
        "Z hotové textové odpovědi vytváří zvuk, který slyšíte. Ovlivňuje "
        "přirozenost, plynulost a rychlost mluvení, ale nemění význam ani obsah "
        "odpovědi. Barva hlasu se vybírá samostatně."
    ),
    "embedding_model": (
        "Převádí texty do interní číselné podoby, díky které Dagmar najde "
        "významově související informace v historii a dlouhodobé paměti. Sám "
        "nevytváří odpověď ani neposlouchá mikrofon."
    ),
    "summary_model": (
        "Po skončení rozhovoru vytváří jeho název a stručné shrnutí. Neúčastní "
        "se živé odpovědi, proto zde obvykle stačí rychlejší a úspornější model."
    ),
}

ROLE_DETAILS = {
    "conversation_model": (
        "Používá se pro hlavní odpovědi. Výkonnější model může být pomalejší nebo dražší."
    ),
    "transcription_model": (
        "Změna se projeví od nového hlasového rozhovoru. Neovlivňuje inteligenci "
        "odpovědi ani barvu hlasu."
    ),
    "speech_model": (
        "Změna se projeví od nového hlasového rozhovoru. Konkrétní barva hlasu zůstává samostatná."
    ),
    "embedding_model": (
        "Změna vyžaduje konzistentní reindexaci; vektory vytvořené různými modely se nesmí míchat."
    ),
    "summary_model": (
        "Nepoužívá se pro živou odpověď a nesmí vytvářet skutečnosti, které v rozhovoru nebyly."
    ),
}

PREFERENCES = {
    "conversation_model": ("gpt-5-mini", "gpt-5-nano", "gpt-4.1-mini", "gpt-4o-mini"),
    "transcription_model": ("gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-1"),
    "speech_model": ("gpt-4o-mini-tts", "tts-1-hd", "tts-1"),
    "embedding_model": (
        "text-embedding-3-large",
        "text-embedding-3-small",
        "text-embedding-ada-002",
    ),
    "summary_model": ("gpt-5-mini", "gpt-5-nano", "gpt-4.1-mini", "gpt-4o-mini"),
}

DENY_MARKERS = (
    "embedding",
    "transcrib",
    "whisper",
    "tts",
    "audio",
    "realtime",
    "image",
    "video",
    "sora",
    "moderation",
    "codex",
    "deep-research",
    "computer-use",
    "fine-tune",
    "ft:",
    "chatgpt",
)


@dataclass(frozen=True, slots=True)
class ClassifiedModel:
    external_id: str
    display_name: str
    roles: frozenset[str]
    capabilities: dict[str, bool]


def _normal(value: str) -> str:
    return value.casefold()


def classify_model(
    external_id: str, display_name: str, advertised: set[str] | frozenset[str]
) -> ClassifiedModel:
    model_id = _normal(external_id)
    advertised_lower = {_normal(value) for value in advertised}
    denied = any(marker in model_id for marker in DENY_MARKERS)
    roles: set[str] = set()
    if model_id == "whisper-1" or "transcrib" in model_id:
        roles.add("transcription_model")
    if "tts" in model_id or model_id in {"tts-1", "tts-1-hd"}:
        roles.add("speech_model")
    if model_id.startswith("text-embedding-") or "embedding" in advertised_lower:
        roles.add("embedding_model")
    if not denied:
        text_family = bool(re.match(r"^(gpt-[345]|o[1345](?:-|$))", model_id))
        explicit_chat = bool({"chat", "responses", "structured_outputs"} & advertised_lower)
        if text_family or explicit_chat:
            roles.update({"conversation_model", "summary_model"})
    # A denylist is always authoritative. Advertised capabilities only add a role
    # for otherwise unknown provider-specific text models; they never define all roles.
    if "transcription_model" in roles:
        roles -= {"conversation_model", "summary_model"}
    if "speech_model" in roles:
        roles -= {"conversation_model", "summary_model"}
    capabilities = {
        "responses": "conversation_model" in roles or "summary_model" in roles,
        "structured_outputs": "conversation_model" in roles or "summary_model" in roles,
        "transcriptions": "transcription_model" in roles,
        "speech": "speech_model" in roles,
        "embeddings": "embedding_model" in roles,
    }
    return ClassifiedModel(external_id, display_name, frozenset(roles), capabilities)


def recommendation_rank(role: str, external_id: str) -> tuple[int, str]:
    preferred = PREFERENCES[role]
    value = _normal(external_id)
    for index, alias in enumerate(preferred):
        if value == alias:
            return index, value
    for index, alias in enumerate(preferred):
        family = alias.rsplit("-", 1)[0]
        if value.startswith(family + "-"):
            return index + 10, value
    return 1000, value
