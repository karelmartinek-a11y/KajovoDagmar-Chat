from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class SettingDefinition:
    area: str
    key: str
    label: str
    description: str
    value_type: Literal["string", "integer", "boolean", "choice", "duration"]
    default: Any
    effect_boundary: Literal[
        "immediate", "next_turn", "new_voice_session", "next_login", "service_restart"
    ]
    choices: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None


DEFINITIONS: tuple[SettingDefinition, ...] = (
    SettingDefinition(
        "general",
        "ui_language",
        "Jazyk rozhraní",
        "Jazyk ovládacích prvků aplikace.",
        "choice",
        "cs",
        "next_login",
        ("cs", "en"),
    ),
    SettingDefinition(
        "general",
        "timezone",
        "Časové pásmo",
        "Časové pásmo pro zobrazení dat a časů.",
        "string",
        "Europe/Prague",
        "immediate",
    ),
    SettingDefinition(
        "conversation",
        "language",
        "Jazyk rozhovoru",
        "Výchozí jazyk hlasové a textové komunikace.",
        "choice",
        "cs",
        "next_turn",
        ("cs", "en", "de"),
    ),
    SettingDefinition(
        "conversation",
        "verbosity",
        "Stručnost odpovědí",
        "Požadovaný rozsah odpovědi bez omezení bezpečnostních informací.",
        "choice",
        "balanced",
        "next_turn",
        ("short", "balanced", "detailed"),
    ),
    SettingDefinition(
        "conversation",
        "idle_warning_seconds",
        "Upozornění na nečinnost",
        "Doba nečinnosti před upozorněním v aktivním rozhovoru.",
        "integer",
        240,
        "new_voice_session",
        minimum=60,
        maximum=1800,
    ),
    SettingDefinition(
        "conversation",
        "idle_end_seconds",
        "Ukončení při nečinnosti",
        "Doba nečinnosti před bezpečným ukončením rozhovoru.",
        "integer",
        300,
        "new_voice_session",
        minimum=120,
        maximum=3600,
    ),
    SettingDefinition(
        "models",
        "conversation_model",
        "Mozek rozhovoru",
        "Rozumí obsahu rozhovoru a připravuje hlavní odpověď; nevytváří zvuk ani "
        "nepřepisuje mikrofon.",
        "string",
        "",
        "next_turn",
    ),
    SettingDefinition(
        "models",
        "transcription_model",
        "Sluch – převod řeči na text",
        "Převádí zvuk z mikrofonu na napsanou větu; nerozhoduje, jak Dagmar odpoví.",
        "string",
        "",
        "new_voice_session",
    ),
    SettingDefinition(
        "models",
        "speech_model",
        "Řeč – převod textu na hlas",
        "Vytváří zvuk z hotové textové odpovědi; barva hlasu se vybírá samostatně.",
        "string",
        "",
        "new_voice_session",
    ),
    SettingDefinition(
        "models",
        "embedding_model",
        "Paměť – hledání souvisejících informací",
        "Pomáhá hledat významově související informace; sám neodpovídá a neposlouchá mikrofon.",
        "string",
        "",
        "immediate",
    ),
    SettingDefinition(
        "models",
        "summary_model",
        "Archivář – názvy a shrnutí",
        "Po skončení rozhovoru vytvoří název a pravdivé stručné shrnutí.",
        "string",
        "",
        "next_turn",
    ),
    SettingDefinition(
        "voice",
        "voice_id",
        "Barva hlasu Dagmar",
        "Určuje, jak Dagmar zní. Není to AI model a nemění chytrost ani obsah odpovědi.",
        "string",
        "",
        "next_turn",
    ),
    SettingDefinition(
        "security",
        "session_idle_minutes",
        "Nečinnost přihlášení",
        "Doba nečinnosti před vypršením relace.",
        "integer",
        30,
        "next_login",
        minimum=10,
        maximum=120,
    ),
    SettingDefinition(
        "voice",
        "output_volume",
        "Hlasitost hlasu",
        "Výchozí hlasitost přehrávání hlasové odpovědi.",
        "integer",
        80,
        "immediate",
        minimum=0,
        maximum=100,
    ),
    SettingDefinition(
        "voice",
        "barge_in",
        "Přerušení řečí",
        "Umožní přerušit hlas asistentky novou replikou.",
        "boolean",
        True,
        "new_voice_session",
    ),
    SettingDefinition(
        "voice",
        "endpoint_silence_ms",
        "Konec repliky",
        "Ticho potřebné pro bezpečné uzavření repliky.",
        "integer",
        900,
        "new_voice_session",
        minimum=500,
        maximum=2500,
    ),
    SettingDefinition(
        "memory",
        "suggestions_enabled",
        "Návrhy na uložení",
        "Asistentka může navrhnout užitečnou vzpomínku; uložení vždy vyžaduje potvrzení.",
        "boolean",
        True,
        "next_turn",
    ),
    SettingDefinition(
        "memory",
        "soft_delete_days",
        "Obnova odstraněné paměti",
        "Počet dnů, po které lze obnovit měkce odstraněnou položku.",
        "integer",
        30,
        "immediate",
        minimum=1,
        maximum=365,
    ),
    SettingDefinition(
        "history",
        "soft_delete_days",
        "Obnova odstraněné historie",
        "Počet dnů, po které lze obnovit odstraněnou konverzaci.",
        "integer",
        30,
        "immediate",
        minimum=1,
        maximum=365,
    ),
    SettingDefinition(
        "history",
        "automatic_summary",
        "Automatické názvy a shrnutí",
        "Po uzavření vytvoří název a pravdivé odvozené shrnutí.",
        "boolean",
        True,
        "next_turn",
    ),
    SettingDefinition(
        "diagnostics",
        "retention_days",
        "Retence diagnostiky",
        "Doba uchování technických logů bez soukromého obsahu.",
        "integer",
        30,
        "immediate",
        minimum=7,
        maximum=90,
    ),
    SettingDefinition(
        "diagnostics",
        "level",
        "Úroveň diagnostiky",
        "Rozsah technických událostí; plný obsah konverzací se neukládá.",
        "choice",
        "standard",
        "immediate",
        ("minimal", "standard", "enhanced"),
    ),
    SettingDefinition(
        "backups",
        "schedule",
        "Plán úplných záloh",
        "Cron výraz řízený produkční orchestrací záloh.",
        "string",
        "0 2 * * *",
        "service_restart",
    ),
)

BY_KEY = {(item.area, item.key): item for item in DEFINITIONS}


def validate_value(definition: SettingDefinition, value: Any) -> Any:
    if definition.value_type in {"integer", "duration"}:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("Hodnota musí být celé číslo.")
        if definition.minimum is not None and value < definition.minimum:
            raise ValueError(f"Nejnižší povolená hodnota je {definition.minimum}.")
        if definition.maximum is not None and value > definition.maximum:
            raise ValueError(f"Nejvyšší povolená hodnota je {definition.maximum}.")
    elif definition.value_type == "boolean" and not isinstance(value, bool):
        raise ValueError("Hodnota musí být ano nebo ne.")
    elif definition.value_type in {"string", "choice"} and not isinstance(value, str):
        raise ValueError("Hodnota musí být text.")
    if definition.choices and value not in definition.choices:
        raise ValueError("Hodnota není v seznamu povolených možností.")
    return value
